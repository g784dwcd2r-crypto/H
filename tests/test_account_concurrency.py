"""Concurrent account operations must survive both threads and independent Postgres connections."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import sleep, time_ns

import pytest

from filings_hub import accounts as A
from filings_hub.lake.storage import Storage


@pytest.fixture(params=["lake", "postgres"])
def stores(request, tmp_path):
    if request.param == "postgres":
        url = request.getfixturevalue("pg_url")
        created = [A.PostgresUserStore(url) for _ in range(8)]
    else:
        created = [A.LakeUserStore(Storage(str(tmp_path))) for _ in range(8)]
    yield created
    for store in created:
        if isinstance(store, A.PostgresUserStore):
            store.conn.close()


def parallel(stores, action):
    barrier = Barrier(len(stores))

    def run(item):
        index, store = item
        barrier.wait(timeout=10)
        return action(store, index)

    with ThreadPoolExecutor(max_workers=len(stores)) as pool:
        return list(pool.map(run, enumerate(stores)))


def test_same_email_first_signins_return_one_account(stores):
    email = f"concurrent-{time_ns()}@example.test"
    users = parallel(stores, lambda store, _: store.create_user(email, {"first_name": "First"}))
    assert len({user.id for user in users}) == 1
    assert all(user.email == email and user.first_name == "First" for user in users)
    assert stores[0].create_user(email.upper(), {"first_name": "Overwrite"}).first_name == "First"


def test_one_magic_link_has_one_successful_redemption(stores, monkeypatch):
    user = stores[0].create_user(f"token-{time_ns()}@example.test")
    token, _ = A.issue_magic_link(stores[0], user.email, "")
    if isinstance(stores[0], A.LakeUserStore):
        # Widen the old read/delete race without relying on a particular thread scheduler.
        for store in stores:
            original = store._read

            def delayed_read(rel, original=original):
                result = original(rel)
                if rel.startswith(A.TOKENS):
                    sleep(0.01)
                return result

            monkeypatch.setattr(store, "_read", delayed_read)
    results = parallel(stores, lambda store, _: A.redeem_magic_link(store, token))
    assert sum(result is not None for result in results) == 1
    assert next(result.id for result in results if result) == user.id


def test_concurrent_distinct_preferences_are_all_retained(stores, monkeypatch):
    user = stores[0].create_user(f"prefs-{time_ns()}@example.test")
    if isinstance(stores[0], A.LakeUserStore):
        for store in stores:
            original = store.list_prefs

            def delayed_read(uid, original=original):
                result = original(uid)
                sleep(0.01)
                return result

            monkeypatch.setattr(store, "list_prefs", delayed_read)
    parallel(stores, lambda store, n: store.put_pref(user.id, A.Pref("global", "", f"key_{n}", n)))
    assert {pref.key: pref.value for pref in stores[0].list_prefs(user.id)} == {
        f"key_{n}": n for n in range(len(stores))
    }


def company(n):
    return {"cik": n + 1, "name": f"Company {n}", "ticker": f"C{n}"}


def test_concurrent_follows_and_removals_preserve_other_companies(stores):
    user = stores[0].create_user(f"watchlist-{time_ns()}@example.test")
    stores[0].put_pref(user.id, A.Pref("global", "", "scale", "billions"))
    parallel(stores, lambda store, n: store.mutate_watchlist(user.id, company(n), "toggle"))
    saved = {p.key: p.value for p in stores[0].list_prefs(user.id)}
    assert {row["cik"] for row in saved["watchlist"]} == set(range(1, len(stores) + 1))
    assert saved["scale"] == "billions"
    # Alternating concurrent removals and additions affect only their requested company.
    parallel(
        stores,
        lambda store, n: store.mutate_watchlist(
            user.id, company(n if n % 2 == 0 else n + 10), "remove" if n % 2 == 0 else "toggle"
        ),
    )
    saved = next(p.value for p in stores[0].list_prefs(user.id) if p.key == "watchlist")
    assert {row["cik"] for row in saved} == {2, 4, 6, 8, 12, 14, 16, 18}


def test_concurrent_toggle_same_company_is_serializable(stores):
    user = stores[0].create_user(f"toggle-{time_ns()}@example.test")
    parallel(stores, lambda store, _: store.mutate_watchlist(user.id, company(0), "toggle"))
    saved = next(p.value for p in stores[0].list_prefs(user.id) if p.key == "watchlist")
    assert saved == []  # Eight successful toggles leave it unfollowed.


def test_watchlist_limit_under_concurrent_additions_and_other_account_isolation(stores):
    user = stores[0].create_user(f"limit-{time_ns()}@example.test")
    other = stores[0].create_user(f"other-{time_ns()}@example.test")
    initial = [company(n) for n in range(A.WATCHLIST_LIMIT - 1)]
    stores[0].put_pref(user.id, A.Pref("global", "", "watchlist", initial))

    def add(store, n):
        try:
            store.mutate_watchlist(user.id, company(A.WATCHLIST_LIMIT + n), "toggle")
            return True
        except ValueError:
            return False

    results = parallel(stores, add)
    assert sum(results) == 1
    saved = next(p.value for p in stores[0].list_prefs(user.id) if p.key == "watchlist")
    assert len(saved) == A.WATCHLIST_LIMIT
    assert stores[0].list_prefs(other.id) == []
    assert len(stores[0].mutate_watchlist(user.id, company(0), "remove")) == A.WATCHLIST_LIMIT - 1
