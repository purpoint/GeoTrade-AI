"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { api, ApiError, post, type Me } from "@/lib/api/client";

/** Current user, or null when signed out. A 401 here is a normal "signed out", not an error. */
export function useMe() {
  return useQuery<Me | null>({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api<Me>("/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
  });
}

export function useAuthActions() {
  const qc = useQueryClient();
  const router = useRouter();
  const signedIn = useCallback(
    (me: Me, next = "/portfolio") => {
      qc.clear();
      qc.setQueryData(["me"], me);
      router.push(next);
    },
    [qc, router],
  );
  return {
    login: async (email: string, password: string, next?: string) =>
      signedIn(await post<Me>("/auth/login", { email, password }), next),
    signup: async (body: { email: string; password: string; display_name?: string; accept_disclaimer: boolean }) =>
      signedIn(await post<Me>("/auth/signup", body), "/onboarding"),
    demo: async () => signedIn(await post<Me>("/auth/demo"), "/portfolio"),
    logout: async () => {
      await post("/auth/logout").catch(() => undefined);
      qc.clear();
      qc.setQueryData(["me"], null);
      router.push("/");
    },
  };
}
