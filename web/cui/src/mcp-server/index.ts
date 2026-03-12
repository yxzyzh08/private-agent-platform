#!/usr/bin/env node
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema, McpError, ErrorCode } from '@modelcontextprotocol/sdk/types.js';
import fetch from 'node-fetch';
import { logger } from '@/services/logger.js';

// Type definitions
interface NotifyResponse {
  success: boolean;
  id: string;
}

interface Permission {
  id: string;
  status: 'pending' | 'approved' | 'denied';
  modifiedInput?: Record<string, unknown>;
  denyReason?: string;
}

interface PermissionsResponse {
  permissions: Permission[];
}

interface QuestionRecord {
  id: string;
  status: 'pending' | 'answered';
  answers?: Record<string, string | string[]>;
}

interface QuestionPollResponse {
  question: QuestionRecord;
}

// MCP tool result type — compatible with SDK's CallToolResult
interface McpToolResult {
  [key: string]: unknown;
  content: Array<{ type: string; text: string }>;
}

// Get CUI server URL from environment
const CUI_SERVER_URL = process.env.CUI_SERVER_URL || `http://localhost:${process.env.CUI_SERVER_PORT || '3001'}`;

// Get CUI streaming ID from environment (passed by ClaudeProcessManager)
const CUI_STREAMING_ID = process.env.CUI_STREAMING_ID;

// Shared constants
const POLL_INTERVAL = 1000; // 1 second
const TIMEOUT = 60 * 60 * 1000; // 1 hour

/**
 * Send a notification POST to the CUI server and return the created ID.
 */
async function sendNotification(url: string, body: Record<string, unknown>, label: string): Promise<string> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const errorText = await response.text();
    logger.error(`Failed to notify CUI server for ${label}`, { status: response.status, error: errorText });
    throw new Error(`Failed to notify CUI server: ${errorText}`);
  }

  const data = await response.json() as NotifyResponse;
  logger.debug(`${label} request created`, { id: data.id, streamingId: CUI_STREAMING_ID });
  return data.id;
}

/**
 * Poll a URL until a check function returns a result, or timeout.
 */
async function pollUntilResolved<T>(
  pollUrl: string,
  checkFn: (data: T) => McpToolResult | null,
  label: string,
): Promise<McpToolResult> {
  const startTime = Date.now();

  while (true) {
    if (Date.now() - startTime > TIMEOUT) {
      logger.warn(`${label} request timed out`, { pollUrl });
      return {
        content: [{ type: 'text', text: JSON.stringify({
          behavior: 'deny',
          message: `${label} request timed out after 1 hour — user did not respond`,
        }) }],
      };
    }

    const pollResponse = await fetch(pollUrl, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!pollResponse.ok) {
      logger.error(`Failed to poll ${label} status`, { status: pollResponse.status });
      throw new Error(`Failed to poll ${label} status: ${pollResponse.status}`);
    }

    const data = await pollResponse.json() as T;
    const result = checkFn(data);
    if (result) {
      return result;
    }

    await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL));
  }
}

// Create MCP server
const server = new Server({
  name: 'cui-permissions',
  version: '1.0.0',
}, {
  capabilities: {
    tools: {},
  },
});

// Define tools
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'approval_prompt',
      description: 'Request approval for tool usage from CUI',
      inputSchema: {
        type: 'object',
        properties: {
          tool_name: {
            type: 'string',
            description: 'The tool requesting permission',
          },
          input: {
            type: 'object',
            description: 'The input for the tool',
          },
        },
        required: ['tool_name', 'input'],
      },
    },
    {
      name: 'ask_user',
      description: 'Ask the user a question with selectable options in CUI. Supports 1-4 questions, each with 2-4 options. Supports single-select and multi-select modes.',
      inputSchema: {
        type: 'object',
        properties: {
          questions: {
            type: 'array',
            description: 'Array of 1-4 questions to ask the user',
            minItems: 1,
            maxItems: 4,
            items: {
              type: 'object',
              properties: {
                question: {
                  type: 'string',
                  description: 'The question text',
                },
                header: {
                  type: 'string',
                  description: 'Short label displayed as a chip/tag (max 12 chars)',
                },
                options: {
                  type: 'array',
                  description: 'Available choices (2-10 options)',
                  minItems: 2,
                  maxItems: 10,
                  items: {
                    type: 'object',
                    properties: {
                      label: { type: 'string', description: 'Display text for the option' },
                      description: { type: 'string', description: 'Explanation of what this option means' },
                      preview: { type: 'string', description: 'Optional preview content (markdown)' },
                    },
                    required: ['label', 'description'],
                  },
                },
                multiSelect: {
                  type: 'boolean',
                  description: 'Whether to allow multiple selections',
                  default: false,
                },
              },
              required: ['question', 'header', 'options', 'multiSelect'],
            },
          },
        },
        required: ['questions'],
      },
    },
  ],
}));

// Handle tool calls
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const toolName = request.params.name;

  if (toolName === 'approval_prompt') {
    return handleApprovalPrompt(request.params.arguments as { tool_name: string; input: Record<string, unknown> });
  }

  if (toolName === 'ask_user') {
    return handleAskUser(request.params.arguments as { questions: unknown[] });
  }

  throw new McpError(ErrorCode.MethodNotFound, `Unknown tool: ${toolName}`);
});

/**
 * Handle approval_prompt tool call.
 * Uses two-phase list-based polling (check pending, then fetch all).
 */
async function handleApprovalPrompt(args: { tool_name: string; input: Record<string, unknown> }): Promise<McpToolResult> {
  const { tool_name, input } = args;

  try {
    logger.debug('MCP Permission request received', { tool_name, input, streamingId: CUI_STREAMING_ID });

    const permissionRequestId = await sendNotification(
      `${CUI_SERVER_URL}/api/permissions/notify`,
      {
        toolName: tool_name,
        toolInput: input,
        streamingId: CUI_STREAMING_ID || 'unknown',
      },
      'Permission',
    );

    const startTime = Date.now();

    while (true) {
      if (Date.now() - startTime > TIMEOUT) {
        logger.warn('Permission request timed out', { tool_name, permissionRequestId });
        return {
          content: [{ type: 'text', text: JSON.stringify({
            behavior: 'deny',
            message: 'Permission request timed out after 1 hour — user did not respond',
          }) }],
        };
      }

      // Poll pending permissions
      const pollResponse = await fetch(
        `${CUI_SERVER_URL}/api/permissions?streamingId=${CUI_STREAMING_ID}&status=pending`,
        { method: 'GET', headers: { 'Content-Type': 'application/json' } },
      );

      if (!pollResponse.ok) {
        throw new Error(`Failed to poll permission status: ${pollResponse.status}`);
      }

      const { permissions } = await pollResponse.json() as PermissionsResponse;
      const permission = permissions.find((p) => p.id === permissionRequestId);

      if (!permission) {
        // Permission no longer pending — fetch all to get the processed result
        const allResponse = await fetch(
          `${CUI_SERVER_URL}/api/permissions?streamingId=${CUI_STREAMING_ID}`,
          { method: 'GET', headers: { 'Content-Type': 'application/json' } },
        );

        if (!allResponse.ok) {
          throw new Error(`Failed to fetch all permissions: ${allResponse.status}`);
        }

        const { permissions: allPermissions } = await allResponse.json() as PermissionsResponse;
        const processed = allPermissions.find((p) => p.id === permissionRequestId);

        if (processed) {
          if (processed.status === 'approved') {
            logger.debug('Permission approved', { tool_name, permissionRequestId });
            return {
              content: [{ type: 'text', text: JSON.stringify({
                behavior: 'allow',
                updatedInput: processed.modifiedInput || input,
              }) }],
            };
          } else if (processed.status === 'denied') {
            logger.debug('Permission denied', { tool_name, permissionRequestId });
            return {
              content: [{ type: 'text', text: JSON.stringify({
                behavior: 'deny',
                message: processed.denyReason || 'The user doesnt want to proceed with this tool use.The tool use was rejected(eg.if it was a file edit, the new_string was NOT written to the file).STOP what you are doing and wait for the user to tell you how to proceed.',
              }) }],
            };
          }
        }
      }

      await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL));
    }

  } catch (error) {
    logger.error('Error processing permission request', { error });
    return {
      content: [{ type: 'text', text: JSON.stringify({
        behavior: 'deny',
        message: `Permission denied due to error: ${error instanceof Error ? error.message : 'Unknown error'}`,
      }) }],
    };
  }
}

/**
 * Handle ask_user tool call.
 * Uses single-record polling via GET /api/questions/:id.
 */
async function handleAskUser(args: { questions: unknown[] }): Promise<McpToolResult> {
  const { questions } = args;

  try {
    logger.debug('MCP AskUser request received', { questionCount: questions.length, streamingId: CUI_STREAMING_ID });

    const questionId = await sendNotification(
      `${CUI_SERVER_URL}/api/questions/notify`,
      {
        questions,
        streamingId: CUI_STREAMING_ID || 'unknown',
      },
      'AskUser',
    );

    return await pollUntilResolved<QuestionPollResponse>(
      `${CUI_SERVER_URL}/api/questions/${questionId}`,
      (data) => {
        const question = data.question;

        if (question.status === 'answered' && question.answers) {
          logger.debug('Question answered', { id: question.id });
          return {
            content: [{ type: 'text', text: JSON.stringify({
              answers: question.answers,
            }) }],
          };
        }

        return null; // Still pending
      },
      'AskUser',
    );
  } catch (error) {
    logger.error('Error processing ask_user request', { error });
    return {
      content: [{ type: 'text', text: JSON.stringify({
        error: `AskUser failed: ${error instanceof Error ? error.message : 'Unknown error'}`,
        answers: {},
      }) }],
    };
  }
}

// Start the server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  logger.info('MCP Permission server started', { cuiServerUrl: CUI_SERVER_URL });
}

main().catch((error) => {
  logger.error('MCP server error', { error });
  process.exit(1);
});
