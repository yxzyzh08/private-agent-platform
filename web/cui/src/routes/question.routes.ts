import { Router } from 'express';
import { CUIError } from '@/types/index.js';
import { RequestWithRequestId } from '@/types/express.js';
import { QuestionTracker } from '@/services/question-tracker.js';
import { createLogger } from '@/services/logger.js';

export function createQuestionRoutes(
  questionTracker: QuestionTracker
): Router {
  const router = Router();
  const logger = createLogger('QuestionRoutes');

  // Notify endpoint - called by MCP server when ask_user is invoked
  router.post('/notify', async (req: RequestWithRequestId, res, next) => {
    const requestId = req.requestId;
    logger.debug('Question notification received', { requestId, body: req.body });

    try {
      const { questions, streamingId } = req.body;

      if (!questions || !Array.isArray(questions) || questions.length === 0) {
        throw new CUIError('MISSING_QUESTIONS', 'questions array is required and must not be empty', 400);
      }

      if (!streamingId) {
        throw new CUIError('MISSING_STREAMING_ID', 'streamingId is required', 400);
      }

      const request = questionTracker.addQuestion(questions, streamingId);

      logger.debug('Question request tracked', {
        requestId,
        questionId: request.id,
        questionCount: questions.length,
        streamingId,
      });

      res.json({ success: true, id: request.id });
    } catch (error) {
      logger.debug('Question notification failed', {
        requestId,
        error: error instanceof Error ? error.message : String(error),
      });
      next(error);
    }
  });

  // Get single question by ID - used by MCP server for polling
  router.get('/:id', async (req: RequestWithRequestId, res, next) => {
    const requestId = req.requestId;
    const { id } = req.params;

    // Skip if id looks like a query (no UUID format) - let the list handler below handle it
    // Actually, express routes are matched in order, so this won't conflict with GET /

    logger.debug('Get question request', { requestId, questionId: id });

    try {
      const question = questionTracker.getQuestion(id);

      if (!question) {
        throw new CUIError('QUESTION_NOT_FOUND', 'Question request not found', 404);
      }

      res.json({ question });
    } catch (error) {
      logger.debug('Get question failed', {
        requestId,
        error: error instanceof Error ? error.message : String(error),
      });
      next(error);
    }
  });

  // List questions - used by frontend for recovery after page refresh
  router.get('/', async (req: RequestWithRequestId, res, next) => {
    const requestId = req.requestId;
    logger.debug('List questions request', { requestId, query: req.query });

    try {
      const { streamingId, status } = req.query as {
        streamingId?: string;
        status?: 'pending' | 'answered';
      };

      const questions = questionTracker.getQuestions({ streamingId, status });

      logger.debug('Questions listed successfully', {
        requestId,
        count: questions.length,
        filter: { streamingId, status },
      });

      res.json({ questions });
    } catch (error) {
      logger.debug('List questions failed', {
        requestId,
        error: error instanceof Error ? error.message : String(error),
      });
      next(error);
    }
  });

  // Answer endpoint - called by frontend when user submits selection
  router.post('/:id/answer', async (req: RequestWithRequestId, res, next) => {
    const requestId = req.requestId;
    const { id } = req.params;

    logger.debug('Question answer request', { requestId, questionId: id, body: req.body });

    try {
      const { answers } = req.body;

      if (!answers || typeof answers !== 'object') {
        throw new CUIError('MISSING_ANSWERS', 'answers object is required', 400);
      }

      const question = questionTracker.getQuestion(id);
      if (!question) {
        throw new CUIError('QUESTION_NOT_FOUND', 'Question request not found', 404);
      }

      if (question.status !== 'pending') {
        throw new CUIError('QUESTION_NOT_PENDING', 'Question has already been answered', 400);
      }

      const updated = questionTracker.answerQuestion(id, answers);

      if (!updated) {
        throw new CUIError('UPDATE_FAILED', 'Failed to update question answer', 500);
      }

      logger.debug('Question answered successfully', { requestId, questionId: id });

      res.json({ success: true });
    } catch (error) {
      logger.debug('Question answer failed', {
        requestId,
        error: error instanceof Error ? error.message : String(error),
      });
      next(error);
    }
  });

  return router;
}
