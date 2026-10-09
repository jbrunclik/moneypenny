/**
 * Unit tests for quiz block rendering and interaction.
 *
 * All evaluation is done by the LLM — the client only collects answers.
 * These tests verify rendering and answer collection, not correctness evaluation.
 */
import { describe, it, expect } from 'vitest';
import { renderQuizBlock, handleQuizOptionClick, handleQuizContinue, handleQuizInputChange } from '@/components/QuizBlock';

describe('renderQuizBlock', () => {
  it('renders multiple-choice quiz with send button', () => {
    const json = JSON.stringify({
      type: 'multiple-choice',
      question: "What does 'Hola' mean?",
      options: ['Goodbye', 'Hello', 'Thank you', 'Please'],
      correct: 1,
    });

    const html = renderQuizBlock(json);
    expect(html).not.toBeNull();
    expect(html).toContain('quiz-multiple-choice');
    expect(html).toContain("What does 'Hola' mean?");
    expect(html).toContain('Goodbye');
    expect(html).toContain('Hello');
    expect(html).toContain('quiz-continue');
    expect(html).toContain('Send answer');
  });

  it('renders fill-blank quiz with send button', () => {
    const json = JSON.stringify({
      type: 'fill-blank',
      question: 'Complete: Je ___ français.',
      answer: 'parle',
      hint: "First person singular of 'parler'",
    });

    const html = renderQuizBlock(json);
    expect(html).not.toBeNull();
    expect(html).toContain('quiz-fill-blank');
    expect(html).toContain('quiz-text-input');
    expect(html).toContain('quiz-continue');
    expect(html).toContain('Send answer');
  });

  it('renders translate quiz with send button', () => {
    const json = JSON.stringify({
      type: 'translate',
      question: "Translate to English: 'Wo ist der Bahnhof?'",
      answer: 'Where is the train station?',
    });

    const html = renderQuizBlock(json);
    expect(html).not.toBeNull();
    expect(html).toContain('quiz-translate');
    expect(html).toContain('quiz-text-input');
    expect(html).toContain('quiz-continue');
    expect(html).toContain('Send answer');
  });

  it('renders batch quiz with send answers button', () => {
    const json = JSON.stringify({
      type: 'batch',
      title: 'Vocabulary Review',
      questions: [
        {
          type: 'multiple-choice',
          question: "What does 'chat' mean in French?",
          options: ['dog', 'cat', 'bird', 'fish'],
          correct: 1,
        },
        {
          type: 'fill-blank',
          question: "Complete: Il ___ beau aujourd'hui.",
          answer: 'fait',
        },
      ],
    });

    const html = renderQuizBlock(json)!;
    expect(html).not.toBeNull();
    expect(html).toContain('quiz-batch');
    expect(html).toContain('Vocabulary Review');
    expect(html).toContain('quiz-continue');
    expect(html).toContain('Send answers');

    // Sub-questions should NOT have individual "Send answer" buttons
    // Only the batch-level "Send answers" button should exist
    const container = document.createElement('div');
    container.innerHTML = html;
    const buttons = container.querySelectorAll('.quiz-continue');
    expect(buttons.length).toBe(1);
    expect(buttons[0].textContent).toBe('Send answers');
  });

  it('returns null for invalid JSON', () => {
    const html = renderQuizBlock('not valid json');
    expect(html).toBeNull();
  });

  it('returns null for missing type', () => {
    const html = renderQuizBlock(JSON.stringify({ question: 'test' }));
    expect(html).toBeNull();
  });

  it('escapes HTML in questions', () => {
    const json = JSON.stringify({
      type: 'multiple-choice',
      question: '<script>alert(1)</script>',
      options: ['a', 'b'],
      correct: 0,
    });

    const html = renderQuizBlock(json);
    expect(html).not.toBeNull();
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
  });
});

describe('handleQuizOptionClick', () => {
  it('selects the clicked option', () => {
    document.body.innerHTML = `
      <div class="quiz-block quiz-multiple-choice">
        <div class="quiz-options">
          <button class="quiz-option" data-index="0">A</button>
          <button class="quiz-option" data-index="1">B</button>
        </div>
      </div>
    `;

    const btn = document.querySelector('.quiz-option[data-index="1"]') as HTMLButtonElement;
    handleQuizOptionClick(btn);

    expect(btn.classList.contains('selected')).toBe(true);
  });

  it('allows changing selection', () => {
    document.body.innerHTML = `
      <div class="quiz-block quiz-multiple-choice">
        <div class="quiz-options">
          <button class="quiz-option" data-index="0">A</button>
          <button class="quiz-option selected" data-index="1">B</button>
        </div>
      </div>
    `;

    const btnA = document.querySelector('.quiz-option[data-index="0"]') as HTMLButtonElement;
    handleQuizOptionClick(btnA);

    expect(btnA.classList.contains('selected')).toBe(true);
    const btnB = document.querySelector('.quiz-option[data-index="1"]') as HTMLButtonElement;
    expect(btnB.classList.contains('selected')).toBe(false);
  });

  it('does not allow selection after answered', () => {
    document.body.innerHTML = `
      <div class="quiz-block quiz-multiple-choice answered">
        <div class="quiz-options">
          <button class="quiz-option" data-index="0">A</button>
          <button class="quiz-option selected" data-index="1">B</button>
        </div>
      </div>
    `;

    const btnA = document.querySelector('.quiz-option[data-index="0"]') as HTMLButtonElement;
    handleQuizOptionClick(btnA);

    expect(btnA.classList.contains('selected')).toBe(false);
  });
});

describe('handleQuizContinue', () => {
  it('does not send if MC has no selection', () => {
    document.body.innerHTML = `
      <div class="quiz-block quiz-batch">
        <div class="quiz-batch-questions">
          <div class="quiz-batch-item">
            <div class="quiz-block quiz-multiple-choice">
              <div class="quiz-options">
                <button class="quiz-option" data-index="0">A</button>
                <button class="quiz-option" data-index="1">B</button>
              </div>
            </div>
          </div>
        </div>
        <button class="quiz-continue">Send answers</button>
      </div>
    `;

    const continueBtn = document.querySelector('.quiz-continue') as HTMLButtonElement;
    handleQuizContinue(continueBtn);

    // Should not mark as answered
    expect(document.querySelector('.quiz-batch')!.classList.contains('answered')).toBe(false);
    // Should mark as incomplete
    expect(document.querySelector('.quiz-multiple-choice')!.classList.contains('quiz-incomplete')).toBe(true);
  });
});

describe('multiple-choice feedback on submit', () => {
  function renderMc(correct: number): HTMLButtonElement {
    document.body.innerHTML = `<div class="message-content">${renderQuizBlock(
      JSON.stringify({ type: 'multiple-choice', question: 'Hola?', options: ['Bye', 'Hello', 'Thanks'], correct })
    )}</div><textarea id="message-input"></textarea><button id="send-btn"></button>`;
    return document.querySelector('.quiz-continue') as HTMLButtonElement;
  }
  const option = (i: number): HTMLElement => document.querySelector(`.quiz-option[data-index="${i}"]`)!;

  it('marks a wrong pick and reveals the right option', () => {
    const btn = renderMc(1);
    handleQuizOptionClick(option(0) as HTMLButtonElement);
    handleQuizContinue(btn);
    expect(option(0).classList.contains('incorrect')).toBe(true);
    expect(option(1).classList.contains('correct')).toBe(true);
    expect(option(2).classList.contains('correct')).toBe(false);
  });

  it('marks a right pick as correct', () => {
    const btn = renderMc(1);
    handleQuizOptionClick(option(1) as HTMLButtonElement);
    handleQuizContinue(btn);
    expect(option(1).classList.contains('correct')).toBe(true);
    expect(document.querySelector('.quiz-option.incorrect')).toBeNull();
  });

  it('gives no feedback before the answer is sent', () => {
    renderMc(1);
    handleQuizOptionClick(option(0) as HTMLButtonElement);
    expect(document.querySelector('.quiz-option.correct, .quiz-option.incorrect')).toBeNull();
  });
});

describe('batch progress', () => {
  it('counts answered questions as they are answered', () => {
    document.body.innerHTML = `<div class="message-content">${renderQuizBlock(
      JSON.stringify({
        type: 'batch',
        title: 'Vocabulary',
        questions: [
          { type: 'multiple-choice', question: 'Hola?', options: ['Bye', 'Hello'], correct: 1 },
          { type: 'translate', question: 'Thanks', answer: 'Gracias' },
          { type: 'fill-blank', question: 'Yo ___', answer: 'hablo' },
        ],
      })
    )}</div>`;
    const progress = (): string => document.querySelector('.quiz-batch-progress')?.textContent ?? '';
    expect(progress()).toBe('0/3 answered');

    handleQuizOptionClick(document.querySelector('.quiz-option[data-index="1"]') as HTMLButtonElement);
    expect(progress()).toBe('1/3 answered');

    const input = document.querySelector('.quiz-translate .quiz-text-input') as HTMLInputElement;
    input.value = 'Gracias';
    handleQuizInputChange(input);
    expect(progress()).toBe('2/3 answered');
  });
});
