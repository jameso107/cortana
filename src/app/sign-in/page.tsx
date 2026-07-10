import { redirect } from "next/navigation";
import { SignInForm } from "@/components/sign-in-form";
import { isAuthenticated } from "@/lib/auth";

export default async function SignInPage() {
  if (await isAuthenticated()) redirect("/");

  return (
    <main className="signin-shell">
      <section className="signin-card">
        <div className="cortana-mark" aria-hidden="true">C</div>
        <p className="eyebrow">Secure personal agent</p>
        <h1>Welcome back.</h1>
        <p className="signin-copy">
          Sign in to reach the OpenAI-powered agent running on your Mac.
        </p>
        <SignInForm />
        <p className="signin-footnote">Your OpenAI key never leaves this computer.</p>
      </section>
    </main>
  );
}
