import React, { useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import { remarkPlugins } from '../shared/markdownComponents';
import * as Checkbox from '@radix-ui/react-checkbox';
import type { QuestionRequest, Question } from '../../types';
import { api } from '../../services/api';

interface AskUserQuestionCardProps {
  questionRequest: QuestionRequest;
  onAnswered: () => void;
}

/**
 * Inline question card rendered in the message stream.
 * Supports single-select, multi-select, Other option, and preview panels.
 */
export function AskUserQuestionCard({ questionRequest, onAnswered }: AskUserQuestionCardProps) {
  const isAnswered = questionRequest.status === 'answered';
  const [selections, setSelections] = useState<Record<string, string | string[]>>({});
  const [otherTexts, setOtherTexts] = useState<Record<string, string>>({});
  const [showOther, setShowOther] = useState<Record<string, boolean>>({});
  const [focusedOption, setFocusedOption] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Check if all questions have a selection
  const allAnswered = questionRequest.questions.every((q, idx) => {
    const key = String(idx);
    const sel = selections[key];
    if (!sel) return false;
    if (Array.isArray(sel)) return sel.length > 0;
    return sel.length > 0;
  });

  const handleSingleSelect = useCallback((questionIdx: number, label: string) => {
    if (isAnswered) return;
    const key = String(questionIdx);
    setSelections(prev => ({ ...prev, [key]: label }));
    setShowOther(prev => ({ ...prev, [key]: false }));
    setFocusedOption(prev => ({ ...prev, [key]: label }));
  }, [isAnswered]);

  const handleMultiSelect = useCallback((questionIdx: number, label: string, checked: boolean) => {
    if (isAnswered) return;
    const key = String(questionIdx);
    setSelections(prev => {
      const current = (prev[key] as string[] | undefined) || [];
      if (checked) {
        return { ...prev, [key]: [...current, label] };
      } else {
        return { ...prev, [key]: current.filter(l => l !== label) };
      }
    });
    if (label !== 'Other') {
      setFocusedOption(prev => ({ ...prev, [key]: label }));
    }
  }, [isAnswered]);

  const handleOtherToggle = useCallback((questionIdx: number, isMulti: boolean) => {
    if (isAnswered) return;
    const key = String(questionIdx);
    if (isMulti) {
      // For multi-select, Other is just another checkbox
      const current = (selections[key] as string[] | undefined) || [];
      const hasOther = current.includes('Other');
      if (hasOther) {
        setSelections(prev => ({ ...prev, [key]: current.filter(l => l !== 'Other') }));
        setShowOther(prev => ({ ...prev, [key]: false }));
      } else {
        setSelections(prev => ({ ...prev, [key]: [...current, 'Other'] }));
        setShowOther(prev => ({ ...prev, [key]: true }));
      }
    } else {
      // For single-select, Other replaces current selection
      setSelections(prev => ({ ...prev, [key]: 'Other' }));
      setShowOther(prev => ({ ...prev, [key]: true }));
      setFocusedOption(prev => ({ ...prev, [key]: '' }));
    }
  }, [isAnswered, selections]);

  const handleSubmit = useCallback(async () => {
    if (!allAnswered || submitting || isAnswered) return;
    setSubmitting(true);
    setSubmitError(null);

    // Build final answers — replace "Other" with the text input
    const finalAnswers: Record<string, string | string[]> = {};
    for (const [key, value] of Object.entries(selections)) {
      if (Array.isArray(value)) {
        finalAnswers[key] = value.map(v => v === 'Other' ? (otherTexts[key] || 'Other') : v);
      } else {
        finalAnswers[key] = value === 'Other' ? (otherTexts[key] || 'Other') : value;
      }
    }

    try {
      await api.answerQuestion(questionRequest.id, finalAnswers);
      onAnswered();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to submit');
    } finally {
      setSubmitting(false);
    }
  }, [allAnswered, submitting, isAnswered, selections, otherTexts, questionRequest.id, onAnswered]);

  // Show answered state from the server
  const displayAnswers = isAnswered ? questionRequest.answers : selections;

  return (
    <div className={`my-3 rounded-lg border ${isAnswered ? 'border-border/50 bg-muted/30' : 'border-accent/50 bg-background'} overflow-hidden`}>
      {/* Header */}
      <div className={`px-4 py-2 text-xs font-semibold uppercase tracking-wider ${isAnswered ? 'text-muted-foreground bg-muted/50' : 'text-accent bg-accent/10'}`}>
        {isAnswered ? 'Answered' : 'Question'}
      </div>

      {/* Questions */}
      <div className="p-4 space-y-4">
        {questionRequest.questions.map((question, qIdx) => (
          <QuestionItem
            key={qIdx}
            question={question}
            questionIdx={qIdx}
            isAnswered={isAnswered}
            selection={displayAnswers?.[String(qIdx)]}
            showOther={showOther[String(qIdx)] || false}
            otherText={otherTexts[String(qIdx)] || ''}
            focusedOption={focusedOption[String(qIdx)] || ''}
            onSingleSelect={handleSingleSelect}
            onMultiSelect={handleMultiSelect}
            onOtherToggle={handleOtherToggle}
            onOtherTextChange={(idx, text) => setOtherTexts(prev => ({ ...prev, [String(idx)]: text }))}
            onOptionFocus={(idx, label) => setFocusedOption(prev => ({ ...prev, [String(idx)]: label }))}
          />
        ))}
      </div>

      {/* Submit */}
      {!isAnswered && (
        <div className="px-4 pb-4">
          {submitError && (
            <div className="text-xs text-red-400 mb-2">{submitError}</div>
          )}
          <button
            onClick={handleSubmit}
            disabled={!allAnswered || submitting}
            className="w-full py-2 px-4 rounded-md text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed bg-accent text-accent-foreground hover:bg-accent/90"
          >
            {submitting ? 'Submitting...' : 'Submit'}
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Question Item ──────────────────────────────────────────

interface QuestionItemProps {
  question: Question;
  questionIdx: number;
  isAnswered: boolean;
  selection: string | string[] | undefined;
  showOther: boolean;
  otherText: string;
  focusedOption: string;
  onSingleSelect: (idx: number, label: string) => void;
  onMultiSelect: (idx: number, label: string, checked: boolean) => void;
  onOtherToggle: (idx: number, isMulti: boolean) => void;
  onOtherTextChange: (idx: number, text: string) => void;
  onOptionFocus: (idx: number, label: string) => void;
}

function QuestionItem({
  question, questionIdx, isAnswered, selection, showOther, otherText, focusedOption,
  onSingleSelect, onMultiSelect, onOtherToggle, onOtherTextChange, onOptionFocus,
}: QuestionItemProps) {
  const hasPreview = question.options.some(o => o.preview);
  const activePreview = hasPreview
    ? question.options.find(o => o.label === focusedOption)?.preview
    : null;

  return (
    <div>
      {/* Header badge + question text */}
      <div className="flex items-start gap-2 mb-2">
        <span className="inline-block px-2 py-0.5 text-[10px] font-semibold uppercase rounded bg-accent/20 text-accent shrink-0">
          {question.header}
        </span>
        <span className="text-sm text-foreground">{question.question}</span>
      </div>

      {/* Options (with optional preview panel) */}
      <div className={hasPreview ? 'flex gap-4' : ''}>
        {/* Options list */}
        <div className={`space-y-1 ${hasPreview ? 'w-1/2 shrink-0' : ''}`}>
          {question.options.map((option) => (
            <OptionRow
              key={option.label}
              label={option.label}
              description={option.description}
              isMulti={question.multiSelect}
              isSelected={
                question.multiSelect
                  ? Array.isArray(selection) && selection.includes(option.label)
                  : selection === option.label
              }
              isAnswered={isAnswered}
              onSelect={() => {
                if (question.multiSelect) {
                  const checked = !(Array.isArray(selection) && selection.includes(option.label));
                  onMultiSelect(questionIdx, option.label, checked);
                } else {
                  onSingleSelect(questionIdx, option.label);
                }
              }}
              onFocus={() => onOptionFocus(questionIdx, option.label)}
              hasPreview={!!option.preview}
            />
          ))}

          {/* Other option */}
          <OptionRow
            label="Other"
            description="Provide a custom answer"
            isMulti={question.multiSelect}
            isSelected={
              question.multiSelect
                ? Array.isArray(selection) && selection.includes('Other')
                : selection === 'Other'
            }
            isAnswered={isAnswered}
            onSelect={() => onOtherToggle(questionIdx, question.multiSelect)}
            onFocus={() => {}}
            hasPreview={false}
          />

          {/* Other text input */}
          {showOther && !isAnswered && (
            <textarea
              className="w-full mt-1 p-2 text-sm bg-muted border border-border rounded-md text-foreground placeholder-muted-foreground resize-none focus:outline-none focus:ring-1 focus:ring-accent"
              placeholder="Type your answer..."
              rows={2}
              value={otherText}
              onChange={(e) => onOtherTextChange(questionIdx, e.target.value)}
            />
          )}
        </div>

        {/* Preview panel */}
        {hasPreview && (
          <div className="w-1/2 border border-border rounded-md p-3 bg-muted/50 overflow-auto max-h-64">
            {activePreview ? (
              <div className="prose prose-sm prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={remarkPlugins}>{activePreview}</ReactMarkdown>
              </div>
            ) : (
              <div className="text-xs text-muted-foreground italic">Select an option to see preview</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Option Row ─────────────────────────────────────────────

interface OptionRowProps {
  label: string;
  description: string;
  isMulti: boolean;
  isSelected: boolean;
  isAnswered: boolean;
  onSelect: () => void;
  onFocus: () => void;
  hasPreview: boolean;
}

function OptionRow({ label, description, isMulti, isSelected, isAnswered, onSelect, onFocus, hasPreview }: OptionRowProps) {
  return (
    <button
      type="button"
      className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-start gap-2.5
        ${isAnswered
          ? isSelected
            ? 'bg-accent/10 text-foreground'
            : 'text-muted-foreground'
          : isSelected
            ? 'bg-accent/15 text-foreground ring-1 ring-accent/50'
            : 'hover:bg-muted text-foreground/80'
        }
        ${isAnswered ? 'cursor-default' : 'cursor-pointer'}
      `}
      onClick={isAnswered ? undefined : onSelect}
      onMouseEnter={hasPreview && !isAnswered ? onFocus : undefined}
      disabled={isAnswered}
    >
      {/* Selection indicator */}
      <span className="mt-0.5 shrink-0">
        {isMulti ? (
          <Checkbox.Root
            className="w-4 h-4 rounded border border-border flex items-center justify-center data-[state=checked]:bg-accent data-[state=checked]:border-accent"
            checked={isSelected}
            disabled={isAnswered}
            tabIndex={-1}
          >
            <Checkbox.Indicator>
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                <path d="M2 5L4 7L8 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </Checkbox.Indicator>
          </Checkbox.Root>
        ) : (
          <span className={`inline-block w-4 h-4 rounded-full border-2 ${isSelected ? 'border-accent bg-accent' : 'border-border'} flex items-center justify-center`}>
            {isSelected && <span className="block w-1.5 h-1.5 rounded-full bg-accent-foreground" />}
          </span>
        )}
      </span>

      {/* Label + description */}
      <span className="flex-1 min-w-0">
        <span className="font-medium">{label}</span>
        {isAnswered && isSelected && <span className="ml-1 text-accent">&#10003;</span>}
        {description && <span className="block text-xs text-muted-foreground mt-0.5">{description}</span>}
      </span>
    </button>
  );
}
