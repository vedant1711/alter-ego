import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useWarnings } from "./useWarnings";

const GRAPH_DOWN = {
  code: "graph_unavailable",
  message: "The knowledge graph is unreachable.",
  action: "Resume the instance.",
};

describe("useWarnings", () => {
  it("shows what the server reports", () => {
    const { result } = renderHook(() => useWarnings());
    act(() => result.current.report([GRAPH_DOWN]));
    expect(result.current.warnings).toEqual([GRAPH_DOWN]);
  });

  it("clears itself once the condition stops being reported", () => {
    // Nobody should have to reload the page after resuming Aura.
    const { result } = renderHook(() => useWarnings());
    act(() => result.current.report([GRAPH_DOWN]));
    act(() => result.current.report([]));
    expect(result.current.warnings).toEqual([]);
  });

  it("treats an absent warnings field as no warnings", () => {
    const { result } = renderHook(() => useWarnings());
    act(() => result.current.report([GRAPH_DOWN]));
    act(() => result.current.report(undefined));
    expect(result.current.warnings).toEqual([]);
  });

  it("keeps a dismissed warning hidden while the condition persists", () => {
    const { result } = renderHook(() => useWarnings());
    act(() => result.current.report([GRAPH_DOWN]));
    act(() => result.current.dismiss("graph_unavailable"));
    expect(result.current.warnings).toEqual([]);

    act(() => result.current.report([GRAPH_DOWN]));
    expect(result.current.warnings).toEqual([]);
  });

  it("shows a dismissed warning again if it clears and later returns", () => {
    // Dismissing means "I have read this", not "never mention it again".
    const { result } = renderHook(() => useWarnings());
    act(() => result.current.report([GRAPH_DOWN]));
    act(() => result.current.dismiss("graph_unavailable"));
    act(() => result.current.report([])); // condition resolved
    act(() => result.current.report([GRAPH_DOWN])); // and came back
    expect(result.current.warnings).toEqual([GRAPH_DOWN]);
  });

  it("dismissing one warning leaves the others visible", () => {
    const other = { code: "graph_auth", message: "Credentials rejected.", action: null };
    const { result } = renderHook(() => useWarnings());
    act(() => result.current.report([GRAPH_DOWN, other]));
    act(() => result.current.dismiss("graph_unavailable"));
    expect(result.current.warnings).toEqual([other]);
  });
});
