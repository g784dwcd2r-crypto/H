import { currentUser } from "@/lib/session";
import HeaderAccount from "./HeaderAccount";

export default async function UserMenu() {
  const user = await currentUser();
  return <HeaderAccount email={user?.email ?? null} />;
}
