/**
 * Quiz Block component for language learning.
 *
 * Renders interactive quiz blocks from ```quiz fenced code blocks in markdown.
 * Supports multiple-choice, fill-blank, translate, and batch quiz types.
 *
 * All evaluation is done by the LLM — the client only collects answers and
 * sends them back as a chat message via the "Send answer(s)" button.
 *
 * Every quiz type (MC, fill-blank, translate, batch) renders a .quiz-continue
 * button. MC options can be changed until the button is clicked. Text inputs
 * are free-form. The button validates all questions have answers, then sends.
 *
 * Click handlers are delegated from the #messages container in events.ts.
 */

import { escapeHtml } from '../utils/dom';
import { createLogger } from '../utils/logger';

const log = createLogger('QuizBlock');

// ============================================================================
// Types
// ============================================================================

interface MultipleChoiceQuiz {
  type: 'multiple-choice';
  question: string;
  options: string[];
  correct: number;
  explanation?: string;
}

interface FillBlankQuiz {
  type: 'fill-blank';
  question: string;
  answer: string;
  hint?: string;
  explanation?: string;
}

interface TranslateQuiz {
  type: 'translate';
  question: string;
  answer: string;
  accept?: string[];
  explanation?: string;
}

interface BatchQuiz {
  type: 'batch';
  title?: string;
  questions: (MultipleChoiceQuiz | FillBlankQuiz | TranslateQuiz)[];
}

type Quiz = MultipleChoiceQuiz | FillBlankQuiz | TranslateQuiz | BatchQuiz;

// ============================================================================
// Rendering
// ============================================================================

/**
 * Render a quiz block from JSON.
 * Returns HTML string or null if parsing fails.
 */
export function renderQuizBlock(jsonStr: string): string | null {
  try {
    const quiz = JSON.parse(jsonStr) as Quiz;
    if (!quiz || !quiz.type) {
      log.warn('Quiz block missing type', { jsonStr: jsonStr.slice(0, 100) });
      return null;
    }
    return renderQuiz(quiz);
  } catch (error) {
    log.warn('Failed to parse quiz JSON', { error, jsonStr: jsonStr.slice(0, 100) });
    return null;
  }
}

function renderQuiz(quiz: Quiz, insideBatch = false): string {
  switch (quiz.type) {
    case 'multiple-choice':
      return renderMultipleChoice(quiz, insideBatch);
    case 'fill-blank':
      return renderFillBlank(quiz, insideBatch);
    case 'translate':
      return renderTranslate(quiz, insideBatch);
    case 'batch':
      return renderBatch(quiz);
    default:
      log.warn('Unknown quiz type', { type: (quiz as Quiz).type });
      return `<div class="quiz-block quiz-error">Unsupported quiz type.</div>`;
  }
}

function renderMultipleChoice(quiz: MultipleChoiceQuiz, insideBatch = false): string {
  const optionsHtml = quiz.options
    .map((opt, i) => {
      return `<button class="quiz-option" data-index="${i}">${escapeHtml(opt)}</button>`;
    })
    .join('');
  const buttonHtml = insideBatch ? '' : '<button class="quiz-continue">Send answer</button>';

  return `
    <div class="quiz-block quiz-multiple-choice">
      <div class="quiz-question">${escapeHtml(quiz.question)}</div>
      <div class="quiz-options">${optionsHtml}</div>
      ${buttonHtml}
    </div>
  `;
}

function renderFillBlank(quiz: FillBlankQuiz, insideBatch = false): string {
  const hintAttr = quiz.hint ? ` placeholder="${escapeHtml(quiz.hint)}"` : ' placeholder="Type your answer..."';
  const buttonHtml = insideBatch ? '' : '<button class="quiz-continue">Send answer</button>';

  return `
    <div class="quiz-block quiz-fill-blank">
      <div class="quiz-question">${escapeHtml(quiz.question)}</div>
      <input type="text" class="quiz-text-input"${hintAttr} autocomplete="off" />
      ${buttonHtml}
    </div>
  `;
}

function renderTranslate(quiz: TranslateQuiz, insideBatch = false): string {
  const buttonHtml = insideBatch ? '' : '<button class="quiz-continue">Send answer</button>';

  return `
    <div class="quiz-block quiz-translate">
      <div class="quiz-question">${escapeHtml(quiz.question)}</div>
      <input type="text" class="quiz-text-input" placeholder="Type your translation..." autocomplete="off" />
      ${buttonHtml}
    </div>
  `;
}

function renderBatch(quiz: BatchQuiz): string {
  const titleHtml = quiz.title ? `<div class="quiz-batch-title">${escapeHtml(quiz.title)}</div>` : '';
  const questionsHtml = quiz.questions.map((q, i) => {
    return `<div class="quiz-batch-item" data-batch-index="${i}">${renderQuiz(q, true)}</div>`;
  }).join('');

  return `
    <div class="quiz-block quiz-batch">
      ${titleHtml}
      <div class="quiz-batch-questions">${questionsHtml}</div>
      <button class="quiz-continue">Send answers</button>
    </div>
  `;
}

// ============================================================================
// Interaction Handlers (called from event delegation)
// ============================================================================

/**
 * Handle multiple-choice option click — toggles selection.
 * User can change their mind until Continue is clicked.
 */
export function handleQuizOptionClick(optionBtn: HTMLButtonElement): void {
  const quizBlock = optionBtn.closest('.quiz-block') as HTMLElement;
  if (!quizBlock || quizBlock.classList.contains('answered')) return;

  // Deselect siblings, select this one
  const siblings = quizBlock.querySelectorAll('.quiz-option');
  for (const sib of siblings) sib.classList.remove('selected');
  optionBtn.classList.add('selected');
}

/**
 * Handle "Send answers" / "Continue" button click.
 * Validates all questions have answers, then sends to chat for LLM evaluation.
 */
export function handleQuizContinue(continueBtn: HTMLButtonElement): void {
  const quizBlock = continueBtn.closest('.quiz-block') as HTMLElement;
  if (!quizBlock || quizBlock.classList.contains('answered')) return;

  // Validate all questions have answers
  const isBatch = quizBlock.classList.contains('quiz-batch');
  const blocks = isBatch
    ? quizBlock.querySelectorAll('.quiz-batch-item .quiz-block')
    : [quizBlock];

  for (const block of blocks) {
    const el = block as HTMLElement;
    if (el.classList.contains('quiz-multiple-choice')) {
      if (!el.querySelector('.quiz-option.selected')) {
        el.classList.add('quiz-incomplete');
        el.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
        setTimeout(() => el.classList.remove('quiz-incomplete'), 1500);
        return;
      }
    } else {
      const input = el.querySelector('.quiz-text-input') as HTMLInputElement;
      if (!input?.value?.trim()) {
        input?.focus();
        el.classList.add('quiz-incomplete');
        el.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
        setTimeout(() => el.classList.remove('quiz-incomplete'), 1500);
        return;
      }
    }
  }

  // Lock the quiz
  quizBlock.classList.add('answered');

  // Build and send results
  const results = collectQuizAnswers(quizBlock);
  const textarea = document.getElementById('message-input') as HTMLTextAreaElement;
  if (textarea) {
    textarea.value = results;
    textarea.dispatchEvent(new Event('input', { bubbles: true }));

    const sendBtn = document.getElementById('send-btn') as HTMLButtonElement;
    if (sendBtn) {
      sendBtn.click();
    }
  }
}

// ============================================================================
// Helpers
// ============================================================================

function collectQuizAnswers(quizBlock: HTMLElement): string {
  const isBatch = quizBlock.classList.contains('quiz-batch');
  const blocks = isBatch
    ? quizBlock.querySelectorAll('.quiz-batch-item .quiz-block')
    : [quizBlock];

  const answers: string[] = [];

  let i = 0;
  for (const block of blocks) {
    i++;
    const el = block as HTMLElement;
    const question = el.querySelector('.quiz-question')?.textContent || '';

    let userAnswer: string;
    if (el.classList.contains('quiz-multiple-choice')) {
      const selected = el.querySelector('.quiz-option.selected');
      userAnswer = selected?.textContent || '(no answer)';
    } else {
      const input = el.querySelector('.quiz-text-input') as HTMLInputElement;
      userAnswer = input?.value?.trim() || '(no answer)';
    }

    answers.push(`${i}. ${question} \u2192 ${userAnswer}`);
  }

  return `My quiz answers:\n\n${answers.join('\n')}`;
}
