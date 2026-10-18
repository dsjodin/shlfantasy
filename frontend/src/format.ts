export const mkr = (n: number) => `${n.toFixed(1).replace(".", ",")} Mkr`;

export const num = (n: number, digits = 1) => n.toFixed(digits).replace(".", ",");

export const signed = (n: number, digits = 1) => `${n > 0 ? "+" : ""}${num(n, digits)}`;

export const date = (iso: string | null) => {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  return d.toLocaleDateString("sv-SE", { day: "numeric", month: "short" });
};

export const dateTime = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("sv-SE", { dateStyle: "short", timeStyle: "short" }) : "–";

export const STATUS_LABELS: Record<string, string> = {
  active: "",
  injured: "Skadad",
  unavailable: "Borta",
};
