import { useState } from "react";
import { useApp } from "../state";

/** Visas när enheten inte har valt profil: "Vem är du?" */
export function ProfilePicker() {
  const { profiles, selectProfile, createProfile } = useApp();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createProfile(name);
      setName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <section className="card profile-picker">
      <h2>{profiles?.length ? "Vem är du?" : "Skapa din profil"}</h2>
      <p className="hint">
        Varje familjemedlem har en egen profil med eget lag, egen bank och egen AI-chatt. Enheten kommer ihåg ditt val.
      </p>
      <div className="profile-list">
        {profiles?.map((p) => (
          <button key={p.id} className="profile-btn" onClick={() => selectProfile(p.id)}>
            <span className="avatar">{p.name.slice(0, 1).toUpperCase()}</span>
            {p.name}
          </button>
        ))}
      </div>
      <form className="chat-input" onSubmit={create}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nytt namn, t.ex. Anna" maxLength={30} />
        <button className="primary" disabled={!name.trim()}>
          Skapa profil
        </button>
      </form>
      {error && <div className="alert error">{error}</div>}
    </section>
  );
}

/** Profilmenyn i headern. */
export function ProfileMenu() {
  const { profile, selectProfile } = useApp();
  if (!profile) return null;
  return (
    <button className="ghost small profile-chip" onClick={() => selectProfile(null)} title="Byt profil">
      <span className="avatar small">{profile.name.slice(0, 1).toUpperCase()}</span>
      {profile.name} ▾
    </button>
  );
}

/** Byt namn på eller ta bort profilen (visas längst ner på Mitt lag). */
export function ProfileSettings() {
  const { profile, renameProfile, deleteProfile } = useApp();
  const [name, setName] = useState(profile?.name ?? "");
  if (!profile) return null;
  return (
    <section className="card">
      <h2>Profil</h2>
      <div className="toolbar">
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={30} />
        <button disabled={!name.trim() || name.trim() === profile.name} onClick={() => void renameProfile(name)}>
          Byt namn
        </button>
        <button
          className="ghost"
          onClick={() => {
            if (confirm(`Ta bort profilen ${profile.name} och dess sparade lag? Det går inte att ångra.`)) void deleteProfile();
          }}
        >
          Ta bort profil
        </button>
      </div>
    </section>
  );
}
