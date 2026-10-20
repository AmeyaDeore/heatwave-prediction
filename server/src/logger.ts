/**
 * Structured logging: one JSON object per line on stderr, the same shape the FastAPI service
 * writes (docs/api/README.md §6), so both services' logs can be read with the same tools.
 * Never log tokens, passwords or request bodies.
 */
import type { LogLevel } from "./config.js";

const ORDER: Record<LogLevel, number> = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40 };

export type LogFields = Record<string, unknown>;
export type LogWriter = (line: string) => void;

export interface Logger {
  debug(msg: string, fields?: LogFields): void;
  info(msg: string, fields?: LogFields): void;
  warning(msg: string, fields?: LogFields): void;
  error(msg: string, fields?: LogFields): void;
  child(name: string): Logger;
}

const stderr: LogWriter = (line) => process.stderr.write(`${line}\n`);

export function createLogger(
  options: { level?: LogLevel; name?: string; write?: LogWriter } = {},
): Logger {
  const { level = "INFO", name = "heatwave_server", write = stderr } = options;
  const emit = (lvl: LogLevel, msg: string, fields: LogFields = {}) => {
    if (ORDER[lvl] < ORDER[level]) return;
    write(
      JSON.stringify({ ts: new Date().toISOString(), level: lvl, logger: name, msg, ...fields }),
    );
  };
  return {
    debug: (msg, fields) => emit("DEBUG", msg, fields),
    info: (msg, fields) => emit("INFO", msg, fields),
    warning: (msg, fields) => emit("WARNING", msg, fields),
    error: (msg, fields) => emit("ERROR", msg, fields),
    child: (child) => createLogger({ level, name: `${name}.${child}`, write }),
  };
}

/** An error's message and stack for an ERROR log line (never sent to the client). */
export function errorFields(error: unknown): LogFields {
  return error instanceof Error
    ? { error: error.message, stack: error.stack }
    : { error: String(error) };
}
