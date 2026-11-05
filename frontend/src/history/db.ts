import type { ChatTurn, StoredConversation } from "./types";

/**
 * Conversations kept in this browser (IndexedDB). Every access is guarded:
 * without IndexedDB (some private windows, blocked site data, a failing
 * quota) the history lives in memory for the session and the Chat works the
 * same, it is only lost on reload. `isPersistent()` tells which.
 */

const DB_NAME = "raglab-history";
const DB_VERSION = 1;
const STORE = "conversations";

const memory = new Map<string, StoredConversation>();
let dbPromise: Promise<IDBDatabase | null> | null = null;
let persistent = true;

function openDb(): Promise<IDBDatabase | null> {
  if (!dbPromise) {
    dbPromise = new Promise<IDBDatabase | null>((resolve) => {
      try {
        if (typeof indexedDB === "undefined") return resolve(null);
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        request.onupgradeneeded = () => {
          const db = request.result;
          if (!db.objectStoreNames.contains(STORE)) {
            db.createObjectStore(STORE, { keyPath: "id" }).createIndex("updated_at", "updated_at");
          }
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => resolve(null);
        request.onblocked = () => resolve(null);
      } catch {
        resolve(null);
      }
    }).then((db) => {
      persistent = db !== null;
      return db;
    });
  }
  return dbPromise;
}

function run<T>(db: IDBDatabase, mode: IDBTransactionMode, act: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    try {
      const transaction = db.transaction(STORE, mode);
      const request = act(transaction.objectStore(STORE));
      transaction.oncomplete = () => resolve(request.result);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    } catch (e) {
      reject(e);
    }
  });
}

/** Whether the history survives a reload (IndexedDB usable). */
export function isPersistent(): boolean {
  return persistent;
}

/** Wait until we know whether IndexedDB is usable. */
export async function storageReady(): Promise<boolean> {
  await openDb();
  return persistent;
}

/** What a turn keeps: not the in-flight state of the request. */
function storable(turn: ChatTurn): ChatTurn {
  const { pipeline: _pipeline, streaming: _streaming, ...rest } = turn;
  return rest;
}

export async function listStored(): Promise<StoredConversation[]> {
  let items: StoredConversation[] = [...memory.values()];
  try {
    const db = await openDb();
    if (db) {
      const stored = await run<StoredConversation[]>(db, "readonly", (store) => store.getAll());
      const ids = new Set(stored.map((c) => c.id));
      // Writes that fell back to memory (a failed put) are listed too.
      items = [...stored, ...items.filter((c) => !ids.has(c.id))];
    }
  } catch {
    // Keep the in-memory copy.
  }
  return items.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

export async function getStored(id: string): Promise<StoredConversation | null> {
  try {
    const db = await openDb();
    if (db) {
      const found = await run<StoredConversation | undefined>(db, "readonly", (store) => store.get(id));
      if (found) return found;
    }
  } catch {
    // Fall through to memory.
  }
  return memory.get(id) ?? null;
}

export async function putStored(conversation: StoredConversation): Promise<void> {
  const value: StoredConversation = { ...conversation, turns: conversation.turns.map(storable) };
  try {
    const db = await openDb();
    if (db) {
      await run(db, "readwrite", (store) => store.put(value));
      memory.delete(value.id);
      return;
    }
  } catch {
    // Quota or a closed database: keep it for the session at least.
    persistent = false;
  }
  memory.set(value.id, value);
}

export async function deleteStored(id: string): Promise<void> {
  memory.delete(id);
  try {
    const db = await openDb();
    if (db) await run(db, "readwrite", (store) => store.delete(id));
  } catch {
    // Nothing more to do: it is gone from memory.
  }
}
