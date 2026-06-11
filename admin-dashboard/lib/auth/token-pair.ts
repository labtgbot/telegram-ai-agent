import { z } from "zod";

import type { TokenPair } from "@/lib/auth/cookies";

const tokenPairSchema = z.object({
  access_token: z.string().trim().min(1),
  refresh_token: z.string().trim().min(1),
  expires_in: z.number().int().positive(),
});

export function parseTokenPair(payload: unknown): TokenPair | null {
  const parsed = tokenPairSchema.safeParse(payload);
  return parsed.success ? parsed.data : null;
}
