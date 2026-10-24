"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { AuthForm } from "@/components/AuthForm";

function Login() {
  const next = useSearchParams().get("next");
  // only same-site paths, never an absolute URL from the query string
  return <AuthForm mode="login" next={next && next.startsWith("/") && !next.startsWith("//") ? next : undefined} />;
}

export default function LoginPage() {
  return (
    <Suspense>
      <Login />
    </Suspense>
  );
}
