import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { QuestionTracker } from '@/services/question-tracker';
import { QuestionRequest, Question } from '@/types';

const sampleQuestions: Question[] = [
  {
    question: 'Which library should we use?',
    header: 'Library',
    options: [
      { label: 'React', description: 'A JavaScript library for building user interfaces' },
      { label: 'Vue', description: 'The progressive JavaScript framework' },
    ],
    multiSelect: false,
  },
];

const multiSelectQuestions: Question[] = [
  {
    question: 'Which features do you want?',
    header: 'Features',
    options: [
      { label: 'Auth', description: 'User authentication' },
      { label: 'DB', description: 'Database integration' },
      { label: 'Cache', description: 'Caching layer' },
    ],
    multiSelect: true,
  },
];

describe('QuestionTracker', () => {
  let tracker: QuestionTracker;

  beforeEach(() => {
    tracker = new QuestionTracker();
  });

  afterEach(() => {
    tracker.clear();
  });

  describe('addQuestion', () => {
    it('should create a question request with pending status', () => {
      const request = tracker.addQuestion(sampleQuestions, 'stream-1');

      expect(request.id).toBeDefined();
      expect(request.streamingId).toBe('stream-1');
      expect(request.questions).toEqual(sampleQuestions);
      expect(request.status).toBe('pending');
      expect(request.timestamp).toBeDefined();
      expect(request.answers).toBeUndefined();
    });

    it('should emit question_request event', () => {
      return new Promise<void>((resolve) => {
        tracker.on('question_request', (request: QuestionRequest) => {
          expect(request.questions).toEqual(sampleQuestions);
          expect(request.streamingId).toBe('stream-1');
          resolve();
        });

        tracker.addQuestion(sampleQuestions, 'stream-1');
      });
    });

    it('should store multiple question requests', () => {
      tracker.addQuestion(sampleQuestions, 'stream-1');
      tracker.addQuestion(multiSelectQuestions, 'stream-2');

      expect(tracker.size()).toBe(2);
    });
  });

  describe('getQuestion', () => {
    it('should return a specific question by ID', () => {
      const request = tracker.addQuestion(sampleQuestions, 'stream-1');
      const found = tracker.getQuestion(request.id);

      expect(found).toBeDefined();
      expect(found!.id).toBe(request.id);
    });

    it('should return undefined for non-existent ID', () => {
      expect(tracker.getQuestion('non-existent')).toBeUndefined();
    });
  });

  describe('getQuestions', () => {
    it('should filter by streamingId', () => {
      tracker.addQuestion(sampleQuestions, 'stream-1');
      tracker.addQuestion(multiSelectQuestions, 'stream-2');

      const results = tracker.getQuestions({ streamingId: 'stream-1' });
      expect(results).toHaveLength(1);
      expect(results[0].streamingId).toBe('stream-1');
    });

    it('should filter by status', () => {
      const q1 = tracker.addQuestion(sampleQuestions, 'stream-1');
      tracker.addQuestion(multiSelectQuestions, 'stream-1');
      tracker.answerQuestion(q1.id, { '0': 'React' });

      const pending = tracker.getQuestions({ status: 'pending' });
      expect(pending).toHaveLength(1);

      const answered = tracker.getQuestions({ status: 'answered' });
      expect(answered).toHaveLength(1);
      expect(answered[0].id).toBe(q1.id);
    });

    it('should return all questions when no filter', () => {
      tracker.addQuestion(sampleQuestions, 'stream-1');
      tracker.addQuestion(multiSelectQuestions, 'stream-2');

      expect(tracker.getQuestions()).toHaveLength(2);
    });
  });

  describe('answerQuestion', () => {
    it('should update status to answered and store answers', () => {
      const request = tracker.addQuestion(sampleQuestions, 'stream-1');
      const answers = { '0': 'React' };

      const result = tracker.answerQuestion(request.id, answers);
      expect(result).toBe(true);

      const updated = tracker.getQuestion(request.id);
      expect(updated!.status).toBe('answered');
      expect(updated!.answers).toEqual(answers);
    });

    it('should emit question_answered event', () => {
      return new Promise<void>((resolve) => {
        const request = tracker.addQuestion(sampleQuestions, 'stream-1');

        tracker.on('question_answered', (answered: QuestionRequest) => {
          expect(answered.id).toBe(request.id);
          expect(answered.status).toBe('answered');
          expect(answered.answers).toEqual({ '0': 'Vue' });
          resolve();
        });

        tracker.answerQuestion(request.id, { '0': 'Vue' });
      });
    });

    it('should return false for non-existent ID', () => {
      expect(tracker.answerQuestion('bad-id', { '0': 'x' })).toBe(false);
    });

    it('should return false if already answered', () => {
      const request = tracker.addQuestion(sampleQuestions, 'stream-1');
      tracker.answerQuestion(request.id, { '0': 'React' });

      expect(tracker.answerQuestion(request.id, { '0': 'Vue' })).toBe(false);
    });

    it('should handle multi-select answers', () => {
      const request = tracker.addQuestion(multiSelectQuestions, 'stream-1');
      const answers = { '0': ['Auth', 'DB'] };

      tracker.answerQuestion(request.id, answers);

      const updated = tracker.getQuestion(request.id);
      expect(updated!.answers).toEqual(answers);
    });
  });

  describe('removeQuestionsByStreamingId', () => {
    it('should remove all questions for the given streamingId', () => {
      tracker.addQuestion(sampleQuestions, 'stream-1');
      tracker.addQuestion(multiSelectQuestions, 'stream-1');
      tracker.addQuestion(sampleQuestions, 'stream-2');

      const removed = tracker.removeQuestionsByStreamingId('stream-1');
      expect(removed).toBe(2);
      expect(tracker.size()).toBe(1);
      expect(tracker.getQuestions({ streamingId: 'stream-1' })).toHaveLength(0);
    });

    it('should return 0 when no matching questions', () => {
      tracker.addQuestion(sampleQuestions, 'stream-1');
      expect(tracker.removeQuestionsByStreamingId('stream-999')).toBe(0);
    });
  });

  describe('clear', () => {
    it('should remove all questions', () => {
      tracker.addQuestion(sampleQuestions, 'stream-1');
      tracker.addQuestion(multiSelectQuestions, 'stream-2');

      tracker.clear();
      expect(tracker.size()).toBe(0);
    });
  });
});
