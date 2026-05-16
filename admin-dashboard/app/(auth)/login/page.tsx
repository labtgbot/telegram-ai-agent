import { Suspense } from "react";

import { LoginForm } from "@/components/auth/login-form";

export const metadata = {
  title: "Sign in — Admin CRM",
};

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
