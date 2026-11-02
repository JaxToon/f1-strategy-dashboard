let currentRole = "strategist";

export function setRole(role: string) {
  currentRole = role;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", "X-Role": currentRole },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Permintaan gagal (${response.status}).`);
  }
  return response.json() as Promise<T>;
}

export const get = <T,>(path: string) => request<T>("GET", path);
export const post = <T,>(path: string, body?: unknown) => request<T>("POST", path, body);

const can: Record<string, string[]> = {
  decide: ["chief", "strategist"],
  lock: ["chief"],
  tag: ["chief", "strategist", "analyst"],
  note: ["chief", "strategist", "race_engineer"],
  calibrate: ["chief", "tyre_engineer"],
  control: ["chief", "strategist", "race_engineer", "tyre_engineer", "analyst"],
};

export const allowed = (role: string, action: string) => can[action]?.includes(role) ?? false;
