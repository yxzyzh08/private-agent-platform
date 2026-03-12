import { describe, it, expect, beforeEach } from 'vitest';
import express from 'express';
import request from 'supertest';
import { createQuestionRoutes } from '@/routes/question.routes';
import { QuestionTracker } from '@/services/question-tracker';
import type { Question } from '@/types';

const sampleQuestions: Question[] = [
  {
    question: 'Which library should we use?',
    header: 'Library',
    options: [
      { label: 'React', description: 'A JavaScript library' },
      { label: 'Vue', description: 'The progressive framework' },
    ],
    multiSelect: false,
  },
];

function createTestApp(tracker: QuestionTracker) {
  const app = express();
  app.use(express.json());
  // Add requestId middleware (mimics cui-server)
  app.use((req: any, _res, next) => {
    req.requestId = 'test-req-id';
    next();
  });
  app.use('/api/questions', createQuestionRoutes(tracker));
  // Error handler
  app.use((err: any, _req: any, res: any, _next: any) => {
    res.status(err.statusCode || 500).json({ error: err.code || 'INTERNAL', message: err.message });
  });
  return app;
}

describe('Question Routes', () => {
  let tracker: QuestionTracker;
  let app: ReturnType<typeof createTestApp>;

  beforeEach(() => {
    tracker = new QuestionTracker();
    app = createTestApp(tracker);
  });

  describe('POST /api/questions/notify', () => {
    it('should create a question and return its id', async () => {
      const res = await request(app)
        .post('/api/questions/notify')
        .send({ questions: sampleQuestions, streamingId: 'stream-1' });

      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      expect(res.body.id).toBeDefined();
      expect(tracker.size()).toBe(1);
    });

    it('should return 400 when questions is missing', async () => {
      const res = await request(app)
        .post('/api/questions/notify')
        .send({ streamingId: 'stream-1' });

      expect(res.status).toBe(400);
      expect(res.body.error).toBe('MISSING_QUESTIONS');
    });

    it('should return 400 when questions is empty array', async () => {
      const res = await request(app)
        .post('/api/questions/notify')
        .send({ questions: [], streamingId: 'stream-1' });

      expect(res.status).toBe(400);
    });

    it('should return 400 when streamingId is missing', async () => {
      const res = await request(app)
        .post('/api/questions/notify')
        .send({ questions: sampleQuestions });

      expect(res.status).toBe(400);
      expect(res.body.error).toBe('MISSING_STREAMING_ID');
    });
  });

  describe('GET /api/questions/:id', () => {
    it('should return a question by id', async () => {
      const q = tracker.addQuestion(sampleQuestions, 'stream-1');

      const res = await request(app).get(`/api/questions/${q.id}`);

      expect(res.status).toBe(200);
      expect(res.body.question.id).toBe(q.id);
      expect(res.body.question.status).toBe('pending');
    });

    it('should return 404 for non-existent id', async () => {
      const res = await request(app).get('/api/questions/non-existent');

      expect(res.status).toBe(404);
      expect(res.body.error).toBe('QUESTION_NOT_FOUND');
    });

    it('should reflect answered status after answer', async () => {
      const q = tracker.addQuestion(sampleQuestions, 'stream-1');
      tracker.answerQuestion(q.id, { '0': 'React' });

      const res = await request(app).get(`/api/questions/${q.id}`);

      expect(res.status).toBe(200);
      expect(res.body.question.status).toBe('answered');
      expect(res.body.question.answers).toEqual({ '0': 'React' });
    });
  });

  describe('GET /api/questions', () => {
    it('should list all questions', async () => {
      tracker.addQuestion(sampleQuestions, 'stream-1');
      tracker.addQuestion(sampleQuestions, 'stream-2');

      const res = await request(app).get('/api/questions');

      expect(res.status).toBe(200);
      expect(res.body.questions).toHaveLength(2);
    });

    it('should filter by streamingId', async () => {
      tracker.addQuestion(sampleQuestions, 'stream-1');
      tracker.addQuestion(sampleQuestions, 'stream-2');

      const res = await request(app).get('/api/questions?streamingId=stream-1');

      expect(res.status).toBe(200);
      expect(res.body.questions).toHaveLength(1);
      expect(res.body.questions[0].streamingId).toBe('stream-1');
    });

    it('should filter by status', async () => {
      const q = tracker.addQuestion(sampleQuestions, 'stream-1');
      tracker.addQuestion(sampleQuestions, 'stream-1');
      tracker.answerQuestion(q.id, { '0': 'React' });

      const res = await request(app).get('/api/questions?status=pending');

      expect(res.status).toBe(200);
      expect(res.body.questions).toHaveLength(1);
    });
  });

  describe('POST /api/questions/:id/answer', () => {
    it('should answer a pending question', async () => {
      const q = tracker.addQuestion(sampleQuestions, 'stream-1');

      const res = await request(app)
        .post(`/api/questions/${q.id}/answer`)
        .send({ answers: { '0': 'React' } });

      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);

      const updated = tracker.getQuestion(q.id);
      expect(updated!.status).toBe('answered');
      expect(updated!.answers).toEqual({ '0': 'React' });
    });

    it('should return 404 for non-existent question', async () => {
      const res = await request(app)
        .post('/api/questions/bad-id/answer')
        .send({ answers: { '0': 'React' } });

      expect(res.status).toBe(404);
    });

    it('should return 400 when answers is missing', async () => {
      const q = tracker.addQuestion(sampleQuestions, 'stream-1');

      const res = await request(app)
        .post(`/api/questions/${q.id}/answer`)
        .send({});

      expect(res.status).toBe(400);
      expect(res.body.error).toBe('MISSING_ANSWERS');
    });

    it('should return 400 when question is already answered', async () => {
      const q = tracker.addQuestion(sampleQuestions, 'stream-1');
      tracker.answerQuestion(q.id, { '0': 'React' });

      const res = await request(app)
        .post(`/api/questions/${q.id}/answer`)
        .send({ answers: { '0': 'Vue' } });

      expect(res.status).toBe(400);
      expect(res.body.error).toBe('QUESTION_NOT_PENDING');
    });
  });
});
