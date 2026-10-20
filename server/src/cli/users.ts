/**
 * `npm run users -- <command>`: manage officials' accounts (Part 15 R2). There is no
 * self-registration; accounts are issued.
 *
 *   list
 *   create <username> --name "Display Name"    password read from stdin (never an argument)
 *   reset-password <username>                  new password read from stdin
 *   disable <username> | enable <username>
 *
 * Example: printf '%s' "$NEW_PASSWORD" | npm run users -- create asha --name "Asha Patil"
 * Exit codes: 0 done, 1 failure, 2 usage or configuration error.
 */
import { hashPassword } from "../auth/service.js";
import { prepareDatabase } from "../bootstrap.js";
import { Catalog, loadPlaces } from "../catalog.js";
import { ConfigError, loadConfig, repoPath } from "../config.js";
import { Database } from "../db.js";
import { Store } from "../db/store.js";
import { normaliseUsername, UserStore } from "../db/users.js";
import { createLogger } from "../logger.js";

const USERNAME = /^[a-z0-9._-]{3,64}$/;
const MIN_PASSWORD = 12;

async function readStdin(): Promise<string> {
  if (process.stdin.isTTY) {
    throw new Error("Pipe the password on stdin, e.g. printf '%s' \"$PW\" | npm run users -- ...");
  }
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks)
    .toString("utf8")
    .replace(/\r?\n$/, "");
}

async function newPassword(): Promise<string> {
  const password = await readStdin();
  if (password.length < MIN_PASSWORD) {
    throw new Error(`The password must be at least ${MIN_PASSWORD} characters.`);
  }
  return password;
}

async function main(argv: string[]): Promise<number> {
  const [command, rawUsername] = argv;
  const username = rawUsername ? normaliseUsername(rawUsername) : undefined;
  const usage = () => {
    console.error(
      "Usage: npm run users -- list | create <username> --name <name> | reset-password <username> | disable <username> | enable <username>",
    );
    return 2;
  };
  if (!command || (command !== "list" && !username)) return usage();
  if (username && !USERNAME.test(username)) {
    console.error("A username is 3-64 characters: lower-case letters, digits, '.', '_' or '-'.");
    return 2;
  }

  let config;
  try {
    config = loadConfig();
  } catch (error) {
    if (error instanceof ConfigError) {
      console.error(error.message);
      return 2;
    }
    throw error;
  }
  const logger = createLogger({ level: "WARNING" });
  const database = new Database(config.MONGODB_URI, logger);
  const users = new UserStore(() => database.native());
  try {
    const catalog = new Catalog(loadPlaces(repoPath(config.MONITORED_REGIONS_FILE)));
    await prepareDatabase(
      config.APP_ENV,
      database,
      new Store(() => database.native()),
      catalog,
      logger,
    );
    switch (command) {
      case "list": {
        for (const u of await users.list()) {
          console.log(
            `${u.active ? "active  " : "disabled"}  ${u.username.padEnd(24)} ${u.display_name}`,
          );
        }
        return 0;
      }
      case "create": {
        const nameAt = argv.indexOf("--name");
        const displayName = nameAt > 0 ? argv[nameAt + 1] : undefined;
        if (!displayName) return usage();
        if (await users.byUsername(username!)) {
          console.error(`'${username}' already exists. Use reset-password or enable.`);
          return 1;
        }
        await users.upsert({
          username: username!,
          display_name: displayName,
          password_hash: await hashPassword(await newPassword()),
        });
        console.log(`Created official '${username}'.`);
        return 0;
      }
      case "reset-password": {
        const ok = await users.setPasswordHash(username!, await hashPassword(await newPassword()));
        console.log(ok ? `Password reset for '${username}'.` : `No account '${username}'.`);
        return ok ? 0 : 1;
      }
      case "disable":
      case "enable": {
        const ok = await users.setActive(username!, command === "enable");
        console.log(ok ? `'${username}' ${command}d.` : `No account '${username}'.`);
        return ok ? 0 : 1;
      }
      default:
        return usage();
    }
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    return 1;
  } finally {
    await database.close();
  }
}

process.exitCode = await main(process.argv.slice(2));
