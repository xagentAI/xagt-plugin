import { chmod, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { homedir } from "node:os";

export interface SavedCredentials {
  accessToken: string;
  refreshToken: string;
  accessExpire: number;
  userId: string;
  scope?: string;
}

export function getConfigDir(): string {
  if (process.platform === "win32" && process.env.APPDATA) {
    return join(process.env.APPDATA, "xagt");
  }
  const xdg = process.env.XDG_CONFIG_HOME;
  if (xdg) {
    return join(xdg, "xagt");
  }
  return join(homedir(), ".config", "xagt");
}

export function getCredentialPath(): string {
  return join(getConfigDir(), "credentials.json");
}

export async function loadCredentials(): Promise<SavedCredentials | null> {
  try {
    const raw = await readFile(getCredentialPath(), "utf8");
    return JSON.parse(raw) as SavedCredentials;
  } catch {
    return null;
  }
}

export async function saveCredentials(credentials: SavedCredentials): Promise<void> {
  const path = getCredentialPath();
  await mkdir(dirname(path), { recursive: true });
  if (process.platform !== "win32") {
    try {
      await chmod(path, 0o600);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }
  // Restrict a newly created credential file before writing tokens into it.
  await writeFile(path, `${JSON.stringify(credentials, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  if (process.platform !== "win32") {
    await chmod(path, 0o600);
  }
}

export async function clearCredentials(): Promise<void> {
  await rm(getCredentialPath(), { force: true });
}
