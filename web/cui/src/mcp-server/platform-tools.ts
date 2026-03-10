#!/usr/bin/env node
/**
 * Platform MCP Server — exposes platform API as MCP Tools for Claude Code.
 *
 * Tools: init_project, submit_phase, get_plan_status, control_task, abort_plan
 *
 * Runs as a separate process, communicates with Claude CLI via stdio (MCP protocol).
 * Calls Platform Backend (FastAPI) over HTTP.
 */
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  McpError,
  ErrorCode,
} from '@modelcontextprotocol/sdk/types.js';

const PLATFORM_API_URL =
  process.env.PLATFORM_API_URL || 'http://localhost:8000';

// --- Helper ---

async function platformFetch(
  path: string,
  method: string = 'GET',
  body?: Record<string, unknown>
): Promise<{ ok: boolean; status: number; data: unknown }> {
  try {
    const options: RequestInit = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (body) {
      options.body = JSON.stringify(body);
    }
    const resp = await fetch(`${PLATFORM_API_URL}${path}`, options);
    const data = await resp.json().catch(() => ({}));
    return { ok: resp.ok, status: resp.status, data };
  } catch (error) {
    return {
      ok: false,
      status: 0,
      data: {
        error: `Platform unreachable: ${error instanceof Error ? error.message : String(error)}`,
      },
    };
  }
}

function toolResult(data: unknown) {
  return {
    content: [{ type: 'text' as const, text: JSON.stringify(data, null, 2) }],
  };
}

function toolError(message: string) {
  return {
    content: [
      {
        type: 'text' as const,
        text: JSON.stringify({ error: message }),
      },
    ],
    isError: true,
  };
}

// --- MCP Server ---

const server = new Server(
  { name: 'platform-tools', version: '1.0.0' },
  { capabilities: { tools: {} } }
);

// List tools
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'init_project',
      description:
        'Initialize a new project with git repository and phase-1.md skeleton',
      inputSchema: {
        type: 'object',
        properties: {
          name: {
            type: 'string',
            description:
              'Project name (alphanumeric, dots, hyphens, underscores)',
          },
          description: {
            type: 'string',
            description: 'Short project description',
          },
          base_path: {
            type: 'string',
            description:
              'Base directory for the project (optional, uses config default)',
          },
        },
        required: ['name'],
      },
    },
    {
      name: 'submit_phase',
      description:
        'Submit a phase-N.md file for execution. Returns plan_id for tracking.',
      inputSchema: {
        type: 'object',
        properties: {
          phase_file: {
            type: 'string',
            description: 'Absolute path to the phase-N.md file',
          },
          repo_path: {
            type: 'string',
            description: 'Absolute path to the project repository',
          },
          source: {
            type: 'string',
            description: 'Source identifier (default: "cui")',
          },
        },
        required: ['phase_file', 'repo_path'],
      },
    },
    {
      name: 'get_plan_status',
      description: 'Query the current execution status of a plan',
      inputSchema: {
        type: 'object',
        properties: {
          plan_id: {
            type: 'string',
            description: 'The plan ID returned by submit_phase',
          },
        },
        required: ['plan_id'],
      },
    },
    {
      name: 'control_task',
      description: 'Retry or skip a specific task in a plan',
      inputSchema: {
        type: 'object',
        properties: {
          plan_id: { type: 'string', description: 'The plan ID' },
          task_id: { type: 'string', description: 'The task ID to control' },
          action: {
            type: 'string',
            enum: ['retry', 'skip'],
            description: 'Action to perform',
          },
          feedback: {
            type: 'string',
            description: 'Optional feedback for retry (only used with retry)',
          },
        },
        required: ['plan_id', 'task_id', 'action'],
      },
    },
    {
      name: 'abort_plan',
      description: 'Abort an executing plan',
      inputSchema: {
        type: 'object',
        properties: {
          plan_id: { type: 'string', description: 'The plan ID to abort' },
        },
        required: ['plan_id'],
      },
    },
  ],
}));

// Handle tool calls
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const params = (args || {}) as Record<string, unknown>;

  switch (name) {
    case 'init_project': {
      const { ok, data } = await platformFetch('/api/projects/init', 'POST', {
        name: params.name,
        description: params.description || '',
        base_path: params.base_path || null,
      });
      return ok ? toolResult(data) : toolError(JSON.stringify(data));
    }

    case 'submit_phase': {
      const { ok, data } = await platformFetch(
        '/api/requirements/from-phase',
        'POST',
        {
          phase_file: params.phase_file,
          repo_path: params.repo_path,
          source: params.source || 'cui',
        }
      );
      return ok ? toolResult(data) : toolError(JSON.stringify(data));
    }

    case 'get_plan_status': {
      const { ok, data } = await platformFetch(
        `/api/requirements/${params.plan_id}`
      );
      return ok ? toolResult(data) : toolError(JSON.stringify(data));
    }

    case 'control_task': {
      const action = params.action as string;
      const path =
        action === 'retry'
          ? `/api/requirements/${params.plan_id}/tasks/${params.task_id}/retry`
          : `/api/requirements/${params.plan_id}/tasks/${params.task_id}/skip`;

      const body: Record<string, unknown> = {};
      if (action === 'retry' && params.feedback) {
        body.feedback = params.feedback;
      }

      const { ok, data } = await platformFetch(path, 'POST', body);
      return ok ? toolResult(data) : toolError(JSON.stringify(data));
    }

    case 'abort_plan': {
      const { ok, data } = await platformFetch(
        `/api/requirements/${params.plan_id}/abort`,
        'POST'
      );
      return ok ? toolResult(data) : toolError(JSON.stringify(data));
    }

    default:
      throw new McpError(ErrorCode.MethodNotFound, `Unknown tool: ${name}`);
  }
});

// Start
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error(
    `[platform-tools] MCP server started, API: ${PLATFORM_API_URL}`
  );
}

main().catch((error) => {
  console.error('[platform-tools] Fatal error:', error);
  process.exit(1);
});
