"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export function SignInForm() {
  const router = useRouter();
  const [accessKey, setAccessKey] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");

    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accessKey }),
      });

      if (!response.ok) {
        setError("That access key was not accepted.");
        return;
      }

      router.replace("/");
      router.refresh();
    } catch {
      setError("Cortana could not reach the authentication service.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="signin-form" onSubmit={submit}>
      <label htmlFor="access-key">Owner access key</label>
      <input
        id="access-key"
        name="access-key"
        type="password"
        autoComplete="current-password"
        value={accessKey}
        onChange={(event) => setAccessKey(event.target.value)}
        placeholder="Paste your Cortana access key"
        autoFocus
      />
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <button type="submit" disabled={pending || accessKey.length < 16}>
        {pending ? "Authenticating…" : "Enter Cortana"}
      </button>
    </form>
  );
}
