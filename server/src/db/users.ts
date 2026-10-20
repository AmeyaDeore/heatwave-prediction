/**
 * Officials' accounts and signed-out tokens on MongoDB (Part 15 R2, Part 08 R2): `users`
 * (bcrypt hash only, unique username) and `revoked_tokens` (TTL index on expiry).
 */
import { randomBytes } from "node:crypto";
import type { mongo } from "mongoose";

export interface UserDoc {
  _id: string;
  username: string;
  display_name: string;
  role: "official";
  password_hash: string;
  active: boolean;
  region_ids: string[];
  created_at: Date;
  updated_at: Date;
}

/** The public view, identical to the FastAPI service's UserOut. */
export interface UserOut {
  id: string;
  username: string;
  display_name: string;
  role: string;
}

export const toUserOut = (u: UserDoc): UserOut => ({
  id: u._id,
  username: u.username,
  display_name: u.display_name,
  role: u.role,
});

export const normaliseUsername = (username: string) => username.trim().toLowerCase();

export class UserStore {
  constructor(private readonly db: () => Promise<mongo.Db>) {}

  private async users() {
    return (await this.db()).collection<UserDoc>("users");
  }
  private async revoked() {
    return (await this.db()).collection<{ _id: string; expires_at: Date }>("revoked_tokens");
  }

  async byUsername(username: string): Promise<UserDoc | null> {
    return (await this.users()).findOne({ username: normaliseUsername(username) });
  }

  async byId(id: string): Promise<UserDoc | null> {
    return (await this.users()).findOne({ _id: id });
  }

  async list(): Promise<UserDoc[]> {
    return (await this.users()).find({}, { sort: { username: 1 } }).toArray();
  }

  /** Create, or update the name/password of, the account with this username. */
  async upsert(user: {
    username: string;
    display_name: string;
    password_hash: string;
    id?: string;
  }): Promise<UserDoc> {
    const users = await this.users();
    const username = normaliseUsername(user.username);
    const now = new Date();
    const existing = await users.findOne({ username });
    if (existing) {
      await users.updateOne(
        { _id: existing._id },
        {
          $set: {
            display_name: user.display_name,
            password_hash: user.password_hash,
            active: true,
            updated_at: now,
          },
        },
      );
      return (await users.findOne({ _id: existing._id }))!;
    }
    const doc: UserDoc = {
      _id: user.id ?? `user_${randomBytes(8).toString("hex")}`,
      username,
      display_name: user.display_name,
      role: "official",
      password_hash: user.password_hash,
      active: true,
      region_ids: [],
      created_at: now,
      updated_at: now,
    };
    await users.insertOne(doc);
    return doc;
  }

  async setActive(username: string, active: boolean): Promise<boolean> {
    const result = await (
      await this.users()
    ).updateOne(
      { username: normaliseUsername(username) },
      { $set: { active, updated_at: new Date() } },
    );
    return result.matchedCount === 1;
  }

  async setPasswordHash(username: string, passwordHash: string): Promise<boolean> {
    const result = await (
      await this.users()
    ).updateOne(
      { username: normaliseUsername(username) },
      { $set: { password_hash: passwordHash, updated_at: new Date() } },
    );
    return result.matchedCount === 1;
  }

  async revoke(jti: string, expiresAt: Date): Promise<void> {
    await (
      await this.revoked()
    ).updateOne({ _id: jti }, { $set: { expires_at: expiresAt } }, { upsert: true });
  }

  async isRevoked(jti: string): Promise<boolean> {
    return (await (await this.revoked()).countDocuments({ _id: jti }, { limit: 1 })) > 0;
  }
}
