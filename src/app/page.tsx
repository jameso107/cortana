import { redirect } from "next/navigation";
import { AssistantConsole } from "@/components/assistant-console";
import { isAuthenticated } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  if (!(await isAuthenticated())) redirect("/sign-in");
  return <AssistantConsole />;
}
