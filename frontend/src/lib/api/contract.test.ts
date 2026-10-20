/**
 * Contract drift check: the contract-shaped fixtures (typed against src/lib/api/types.ts) must
 * carry every field docs/api/openapi.json requires and nothing it doesn't define. When the
 * backend schema changes, this fails until types.ts and the fixtures follow.
 */
import { describe, expect, it } from "vitest";
import openapi from "../../../../docs/api/openapi.json";
import { SAMPLE_ALERT, SAMPLE_FACTORS, SAMPLE_PREDICTION, SAMPLE_REGION } from "@/design/fixtures";

type Schema = { properties?: Record<string, unknown>; required?: string[] };
const schemas = openapi.components.schemas as Record<string, Schema>;

function expectMatches(schemaName: string, sample: object) {
  const schema = schemas[schemaName];
  expect(schema, `${schemaName} missing from openapi.json`).toBeDefined();
  const defined = Object.keys(schema!.properties ?? {}).sort();
  const keys = Object.keys(sample).sort();
  expect(
    keys.filter((k) => !defined.includes(k)),
    `${schemaName}: fields the API doesn't define`,
  ).toEqual([]);
  expect(
    (schema!.required ?? []).filter((k) => !keys.includes(k)),
    `${schemaName}: required fields missing`,
  ).toEqual([]);
}

describe("frontend types match docs/api/openapi.json", () => {
  it.each([
    ["RegionOut", SAMPLE_REGION],
    ["PredictionOut", SAMPLE_PREDICTION],
    ["ExplanationOut", SAMPLE_PREDICTION.explanation],
    ["FactorOut", SAMPLE_FACTORS[0]!],
    ["ForecastWindow", SAMPLE_PREDICTION.forecast_window],
    ["WeatherProvenance", SAMPLE_PREDICTION.weather],
    ["AlertOut", SAMPLE_ALERT],
    ["ChannelDelivery", SAMPLE_ALERT.channels[0]!],
    ["DeliverySummary", SAMPLE_ALERT.delivery_summary],
  ] as [string, object][])("%s", (name, sample) => expectMatches(name, sample));

  it("uses the API's risk-class and status enums", () => {
    const risk = (schemas.PredictionOut!.properties!.risk_class as { enum: string[] }).enum;
    expect(risk.sort()).toEqual(["HEATWAVE", "NORMAL", "SEVERE_HEATWAVE"]);
    const status = (schemas.ChannelDelivery!.properties!.status as { enum: string[] }).enum;
    expect(status.sort()).toEqual(["FAILED", "NOTIFIED", "PENDING", "READY"]);
  });
});
