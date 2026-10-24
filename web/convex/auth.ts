import { Password } from "@convex-dev/auth/providers/Password";
import { convexAuth } from "@convex-dev/auth/server";

export const { auth, signIn, signOut, store, isAuthenticated } = convexAuth({
  providers: [
    Password({
      profile(params) {
        return {
          email: String(params.email).trim().toLowerCase(),
          ...(params.name ? { name: String(params.name).trim() } : {}),
        };
      },
    }),
  ],
});
