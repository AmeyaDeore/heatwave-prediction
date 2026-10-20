/**
 * The MongoDB connection (Part 01 R2, Part 08 R2). Step 1 only connects and pings. Collections,
 * validators and indexes arrive with the Part 08 R2 migrations.
 *
 * A database that is down at startup does not stop the API: liveness stays up, readiness
 * reports `database: "unavailable"` with a 503, and the next readiness check tries again.
 */
import mongoose, { type Connection, type mongo } from "mongoose";
import { redactUri } from "./config.js";
import { errorFields, type Logger } from "./logger.js";

/** What the HTTP layer needs from the database; tests pass a fake. */
export interface DatabaseHealth {
  ping(): Promise<boolean>;
}

export interface ServerInfo {
  version: string;
  database: string;
  collections: number;
}

export class Database implements DatabaseHealth {
  private connection: Connection | null = null;
  private connecting: Promise<Connection> | null = null;

  constructor(
    private readonly uri: string,
    private readonly logger: Logger,
    private readonly timeoutMs = 3_000,
  ) {}

  /** Connect, or reuse the open connection. Rejects if MongoDB cannot be reached in time. */
  async connect(): Promise<Connection> {
    if (this.connection?.readyState === mongoose.ConnectionStates.connected) return this.connection;
    this.connecting ??= this.open().finally(() => {
      this.connecting = null;
    });
    return this.connecting;
  }

  private async open(): Promise<Connection> {
    await this.discard();
    const connection = mongoose.createConnection(this.uri, {
      serverSelectionTimeoutMS: this.timeoutMs,
      connectTimeoutMS: this.timeoutMs,
      // Fail fast instead of queueing operations while disconnected.
      bufferCommands: false,
      autoIndex: false,
    });
    try {
      await connection.asPromise();
    } catch (error) {
      await connection.close(true).catch(() => undefined);
      throw error;
    }
    this.connection = connection;
    this.logger.info("database connected", {
      uri: redactUri(this.uri),
      database: connection.name,
    });
    return connection;
  }

  /** The database handle for the store and migrations (connects if needed). */
  async native(): Promise<mongo.Db> {
    const connection = await this.connect();
    return connection.db!;
  }

  /** True when MongoDB answers a ping within the timeout. Never throws. */
  async ping(): Promise<boolean> {
    try {
      const connection = await this.connect();
      await connection.db!.admin().ping({ maxTimeMS: this.timeoutMs });
      return true;
    } catch (error) {
      this.logger.warning("database ping failed", errorFields(error));
      return false;
    }
  }

  /** Read-only facts for the connectivity check. Writes nothing. */
  async info(): Promise<ServerInfo> {
    const connection = await this.connect();
    const db = connection.db!;
    const build = await db.admin().command({ buildInfo: 1 });
    const collections = await db.listCollections({}, { nameOnly: true }).toArray();
    return {
      version: String(build.version),
      database: db.databaseName,
      collections: collections.length,
    };
  }

  async close(): Promise<void> {
    await this.discard();
  }

  private async discard(): Promise<void> {
    const connection = this.connection;
    this.connection = null;
    if (connection) await connection.close().catch(() => undefined);
  }
}
