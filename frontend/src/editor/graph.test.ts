import { describe, expect, it } from "vitest";
import { duration, shortId, timeAgo } from "../lib/format";
import type { DefEdge, NodeSpec } from "../lib/types";
import { checkConnection, createNode, isFieldVisible, outputPorts, uniqueName, wouldCreateCycle } from "./graph";

const spec = (partial: Partial<NodeSpec>): NodeSpec =>
  ({ type: "x", label: "X", category: "data", description: "", icon: "", is_trigger: false, multi_input: false, dynamic_outputs: false, inputs: [{ id: "main", label: "", data_type: "any" }], outputs: [{ id: "main", label: "", data_type: "any" }], fields: [], input_schema: {}, output_schema: {}, defaults: {}, requires_integration: null, ...partial }) as NodeSpec;

const byType: Record<string, NodeSpec> = {
  trigger: spec({ type: "trigger", is_trigger: true, inputs: [] }),
  step: spec({ type: "step" }),
  list: spec({ type: "list", outputs: [{ id: "main", label: "", data_type: "array" }] }),
  needsObject: spec({ type: "needsObject", inputs: [{ id: "main", label: "", data_type: "object" }] }),
  "logic.switch": spec({ type: "logic.switch" }),
};
const n = (id: string, type: string) => ({ id, type, name: id, config: {}, settings: {} });
const e = (source: string, target: string, source_port = "main"): DefEdge => ({ id: `${source}-${target}`, source, source_port, target, target_port: "main" });

describe("checkConnection", () => {
  const nodes = [n("t", "trigger"), n("a", "step"), n("b", "step"), n("l", "list"), n("o", "needsObject")];
  it("allows valid links", () => expect(checkConnection(nodes, [], byType, { source: "t", target: "a" }).ok).toBe(true));
  it("rejects self links", () => expect(checkConnection(nodes, [], byType, { source: "a", target: "a" }).ok).toBe(false));
  it("rejects edges into triggers", () => expect(checkConnection(nodes, [], byType, { source: "a", target: "t" }).reason).toMatch(/trigger/));
  it("rejects duplicates", () => expect(checkConnection(nodes, [e("t", "a")], byType, { source: "t", target: "a" }).reason).toMatch(/already/));
  it("rejects cycles", () => expect(checkConnection(nodes, [e("a", "b")], byType, { source: "b", target: "a" }).reason).toMatch(/cycle/));
  it("rejects incompatible types", () => expect(checkConnection(nodes, [], byType, { source: "l", target: "o" }).reason).toMatch(/array/));
});

describe("graph helpers", () => {
  it("detects cycles across several hops", () => {
    expect(wouldCreateCycle([e("a", "b"), e("b", "c")], "c", "a")).toBe(true);
    expect(wouldCreateCycle([e("a", "b"), e("b", "c")], "a", "c")).toBe(false);
  });
  it("derives switch and error ports from config", () => {
    const ports = outputPorts(byType["logic.switch"], { cases: [{ equals: "x" }, { label: "Y" }] }, { on_error: "error_branch" });
    expect(ports.map((p) => p.id)).toEqual(["case_0", "case_1", "default", "error"]);
    expect(ports[0].label).toBe("x");
  });
  it("names and creates nodes uniquely", () => {
    expect(uniqueName("Delay", ["Delay", "Delay 2"])).toBe("Delay 3");
    const node = createNode(spec({ type: "data.set", label: "Set", defaults: { a: [1] } }), { x: 1, y: 2 }, []);
    expect(node.id).toMatch(/^set_/);
    expect(node.config).toEqual({ a: [1] });
    expect(node.settings?.on_error).toBe("stop");
  });
  it("respects visible_if, including defaults", () => {
    const s = spec({ defaults: { mode: "regex" } });
    expect(isFieldVisible({ visible_if: { mode: ["regex"] } }, {}, s)).toBe(true);
    expect(isFieldVisible({ visible_if: { mode: ["regex"] } }, { mode: "email" }, s)).toBe(false);
  });
});

describe("format", () => {
  it("formats durations", () => {
    expect(duration(null)).toBe("-");
    expect(duration(120)).toBe("120 ms");
    expect(duration(2500)).toBe("2.50 s");
    expect(duration(125_000)).toBe("2m 5s");
  });
  it("formats ids and times", () => {
    expect(shortId("ex_0123456789abcdef")).toBe("ex_01234567...");
    const now = Date.parse("2027-01-01T12:00:00Z");
    expect(timeAgo("2027-01-01T11:00:00Z", now)).toBe("1h ago");
    expect(timeAgo(null)).toBe("Never");
  });
});
