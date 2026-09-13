import Link from "next/link";
import { currentUser } from "@/lib/session";

export default async function UserMenu() {
  const user = await currentUser();
  if (!user)
    return (
      <Link href="/signin" className="user">
        Sign in
      </Link>
    );
  return (
    <span className="user">
      <Link href="/settings" title={user.email}>
        {user.email}
      </Link>
      <form action="/api/auth/signout" method="post" className="inline">
        <button type="submit" className="linkbtn">Sign out</button>
      </form>
    </span>
  );
}
