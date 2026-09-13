import WatchlistView from "@/components/WatchlistView";

export const metadata = { title: "Watchlist · Filings Hub" };

export default function WatchlistPage() {
  return (
    <>
      <p className="eyebrow">Watchlist</p>
      <h1>What your companies filed</h1>
      <p className="lead">Follow companies from their pages. This is the morning view: results filings first, everything else below, and an email when results land.</p>
      <WatchlistView />
    </>
  );
}
