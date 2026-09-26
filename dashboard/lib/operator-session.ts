// Memory only: refresh/closing this tab clears the operator credential.
let token = "";

export function setOperatorToken(value: string): void {
  token = value.trim();
}

export function operatorHeaders(): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}
