// Coordinator sign-in. Two clearly separated modes, chosen by the backend (/api/runtime):
//  - "cognito": Amazon Cognito user pool (USER_PASSWORD_AUTH over HTTPS to cognito-idp, ID token sent to the API).
//  - "local-dev-signin": a LOCAL DEVELOPMENT login with no password; labelled in the UI, refused on AWS.

export interface Session {
  token: string;
  refreshToken?: string;
  expiresAt: number; // epoch ms
  name: string;
  email?: string | null;
  method: "cognito" | "local";
}

const KEY = "airwindow.session.v1";

export function loadSession(): Session | null {
  try {
    const s = JSON.parse(localStorage.getItem(KEY) || "null") as Session | null;
    if (s && s.token && s.expiresAt > Date.now() + 30_000) return s;
    if (s?.refreshToken) return s; // may be refreshed
  } catch {
    /* ignore */
  }
  return null;
}

export function saveSession(s: Session | null) {
  try {
    if (s) localStorage.setItem(KEY, JSON.stringify(s));
    else localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

function decodeJwt(token: string): Record<string, unknown> {
  try {
    const body = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(decodeURIComponent(escape(atob(body))));
  } catch {
    return {};
  }
}

export interface CognitoConfig {
  region: string;
  client_id: string;
}

async function cognito(cfg: CognitoConfig, target: string, body: unknown) {
  const res = await fetch(`https://cognito-idp.${cfg.region}.amazonaws.com/`, {
    method: "POST",
    headers: { "Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}` },
    body: JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((json as { message?: string }).message || `Cognito error ${res.status}`);
  return json as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
}

function sessionFromAuth(r: Record<string, any>, refresh?: string): Session { // eslint-disable-line @typescript-eslint/no-explicit-any
  const a = r.AuthenticationResult;
  if (!a?.IdToken) throw new Error("Additional sign-in steps are required (not supported in this MVP).");
  const claims = decodeJwt(a.IdToken);
  return {
    token: a.IdToken,
    refreshToken: a.RefreshToken ?? refresh,
    expiresAt: Date.now() + (a.ExpiresIn ?? 3600) * 1000,
    name: String(claims.name ?? claims.email ?? "Coordinator"),
    email: (claims.email as string) ?? null,
    method: "cognito",
  };
}

export const cognitoAuth = {
  signIn: async (cfg: CognitoConfig, email: string, password: string) =>
    sessionFromAuth(await cognito(cfg, "InitiateAuth", { AuthFlow: "USER_PASSWORD_AUTH", ClientId: cfg.client_id, AuthParameters: { USERNAME: email, PASSWORD: password } })),
  signUp: (cfg: CognitoConfig, email: string, password: string, name: string) =>
    cognito(cfg, "SignUp", { ClientId: cfg.client_id, Username: email, Password: password, UserAttributes: [{ Name: "email", Value: email }, { Name: "name", Value: name }] }),
  confirm: (cfg: CognitoConfig, email: string, code: string) => cognito(cfg, "ConfirmSignUp", { ClientId: cfg.client_id, Username: email, ConfirmationCode: code }),
  refresh: async (cfg: CognitoConfig, s: Session) =>
    sessionFromAuth(await cognito(cfg, "InitiateAuth", { AuthFlow: "REFRESH_TOKEN_AUTH", ClientId: cfg.client_id, AuthParameters: { REFRESH_TOKEN: s.refreshToken } }), s.refreshToken),
};
