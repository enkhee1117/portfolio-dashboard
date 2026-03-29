import { redirect } from "next/navigation";
export default function TradesRedirect() {
  redirect("/portfolio?tab=trades");
}
