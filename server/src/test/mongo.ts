/**
 * A throwaway MongoDB for tests (mongodb-memory-server). Tests never touch a developer's real
 * MongoDB. The binary version is pinned to the 7.0 series used locally and in deployment.
 */
import { MongoMemoryServer } from "mongodb-memory-server";

export const TEST_MONGODB_VERSION = "7.0.14";

export async function startTestMongo(): Promise<{
  uri: (db: string) => string;
  stop: () => Promise<void>;
}> {
  const server = await MongoMemoryServer.create({ binary: { version: TEST_MONGODB_VERSION } });
  const base = server.getUri().replace(/\/$/, "");
  return {
    uri: (db) => `${base}/${db}`,
    stop: async () => {
      await server.stop();
    },
  };
}
