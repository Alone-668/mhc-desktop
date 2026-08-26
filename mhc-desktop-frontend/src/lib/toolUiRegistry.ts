// Tool-call UI registry.
//
// Each MCP server slug can register a Vue component that takes over
// rendering for its tool calls. Components registered here are
// looked up by the ``<ToolCallCapsule>`` wrapper. Anything not
// registered falls back to the generic name + args + result panel
// inside the capsule itself.
//
// To register a custom UI for the dummy MCP's "add" tool:
//
//   import ToolUiRegistry from "@/lib/toolUiRegistry"
//   ToolUiRegistry.register("dummy-mcp::add", MyAddToolUI)
//
// The component receives the same props the capsule does:
//   { name, status, args, result, error, slug, shortName }
//
// This is intentionally minimal — no slots, no dynamic imports, no
// permission gates. Real apps will want a proper plugin system; for
// now the registry is a process-local Map keyed by the namespaced
// tool name.

import type { Component } from "vue"

type ToolCallProps = {
  name: string
  status: "pending" | "executing" | "success" | "error"
  args: Record<string, unknown>
  result?: string
  error?: string
  slug: string
  shortName: string
}

export type ToolCallComponent = Component & {
  // no extra constraints — Vue handles the rest
}

class ToolUiRegistryImpl {
  private components = new Map<string, ToolCallComponent>()

  /** Register a custom UI for a specific tool call. ``name`` should be
   *  the fully-qualified name ``"<mcp-slug>::<tool-name>"`` to avoid
   *  collisions across MCPs. */
  register(name: string, component: ToolCallComponent): void {
    this.components.set(name, component)
  }

  /** Returns the registered component for ``name`` or null. */
  get(name: string): ToolCallComponent | null {
    return this.components.get(name) ?? null
  }

  /** Clear all registrations. Test helper. */
  clear(): void {
    this.components.clear()
  }

  /** Number of registered components. */
  size(): number {
    return this.components.size
  }
}

export const toolUiRegistry = new ToolUiRegistryImpl()
export type { ToolCallProps }