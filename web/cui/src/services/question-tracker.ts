import { EventEmitter } from 'events';
import { v4 as uuidv4 } from 'uuid';
import { QuestionRequest, Question } from '@/types/index.js';
import { createLogger } from '@/services/logger.js';

const logger = createLogger('QuestionTracker');

/**
 * Service to track AskUserQuestion requests from Claude CLI via MCP.
 * Mirrors PermissionTracker pattern for consistency.
 */
export class QuestionTracker extends EventEmitter {
  private questionRequests: Map<string, QuestionRequest> = new Map();

  constructor() {
    super();
  }

  /**
   * Add a new question request
   */
  addQuestion(questions: Question[], streamingId: string): QuestionRequest {
    const id = uuidv4();
    const request: QuestionRequest = {
      id,
      streamingId,
      questions,
      timestamp: new Date().toISOString(),
      status: 'pending',
    };

    this.questionRequests.set(id, request);
    logger.info('Question request added', { id, questionCount: questions.length, streamingId });

    this.emit('question_request', request);

    return request;
  }

  /**
   * Get a single question request by ID
   */
  getQuestion(id: string): QuestionRequest | undefined {
    return this.questionRequests.get(id);
  }

  /**
   * Get question requests filtered by criteria
   */
  getQuestions(filter?: { streamingId?: string; status?: 'pending' | 'answered' }): QuestionRequest[] {
    let requests = Array.from(this.questionRequests.values());

    if (filter?.streamingId) {
      requests = requests.filter(req => req.streamingId === filter.streamingId);
    }

    if (filter?.status) {
      requests = requests.filter(req => req.status === filter.status);
    }

    return requests;
  }

  /**
   * Answer a question request
   */
  answerQuestion(id: string, answers: Record<string, string | string[]>): boolean {
    const request = this.questionRequests.get(id);
    if (!request) {
      logger.warn('Question request not found', { id });
      return false;
    }

    if (request.status !== 'pending') {
      logger.warn('Question request not pending', { id, status: request.status });
      return false;
    }

    request.status = 'answered';
    request.answers = answers;

    logger.info('Question request answered', { id, streamingId: request.streamingId });
    this.emit('question_answered', request);

    return true;
  }

  /**
   * Remove all questions for a specific streaming ID.
   * Used for cleanup when a conversation ends.
   */
  removeQuestionsByStreamingId(streamingId: string): number {
    const toRemove: string[] = [];

    for (const [id, request] of this.questionRequests.entries()) {
      if (request.streamingId === streamingId) {
        toRemove.push(id);
      }
    }

    toRemove.forEach(id => this.questionRequests.delete(id));

    if (toRemove.length > 0) {
      logger.info('Removed questions for streaming session', {
        streamingId,
        removedCount: toRemove.length,
      });
    }

    return toRemove.length;
  }

  /**
   * Clear all question requests (for testing)
   */
  clear(): void {
    this.questionRequests.clear();
  }

  /**
   * Get the number of question requests
   */
  size(): number {
    return this.questionRequests.size;
  }
}
