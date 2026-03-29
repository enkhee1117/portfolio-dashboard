import { redirect } from "next/navigation";
export default function AssetsRedirect() {
  redirect("/portfolio?tab=assets");
}
