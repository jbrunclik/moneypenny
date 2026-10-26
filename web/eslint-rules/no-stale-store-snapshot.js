/**
 * F2 (docs/conventions.md): re-read `useStore.getState()` after any `await`.
 *
 * Zustand replaces the state object on every `set`, so a snapshot taken with
 * `const store = useStore.getState()` keeps the field values of that moment.
 * Once the function awaits, the user may have switched conversations, another
 * device's sync may have landed, or a concurrent send may have finished - and
 * `store.currentConversation` still answers with the old value. Actions on the
 * snapshot stay correct: they are created once and read fresh state through
 * Zustand's `get()`.
 *
 * Heuristic. A snapshot is a variable initialised (or reassigned) from
 * `useStore.getState()`, either whole (`const store = ...`) or destructured
 * (`const { a, b } = ...`). A read of it is flagged when
 *   - it reads a member of a whole snapshot (`store.field`) or a destructured
 *     binding (`a`), and that value is not called - a call is an action
 *     (`store.setX(...)`, `store.getMessagesPagination(id)`); and
 *   - an `await` (or `for await`) lies between the snapshot and the read: after
 *     the latest (re)assignment in source order and before the read, or anywhere
 *     in a loop that encloses the read and starts after the snapshot (the next
 *     iteration runs after it), in the snapshot's function or in a function
 *     nested between the snapshot and the read; or
 *   - the read sits in a callback passed to `.then` / `.catch` / `.finally`.
 *
 * Known gaps (not flagged):
 *   - sync callbacks that run later (`setTimeout`, event listeners, `onClick`)
 *     reading a snapshot from the enclosing function;
 *   - a snapshot passed whole to another function (`render(store)`) or stored
 *     in an object, and reads through it there;
 *   - snapshots from other stores, or `getState()` reached through an alias;
 *   - a member that is a function but read without a call (`const f = store.setX`)
 *     is flagged although harmless - call it directly or re-read instead.
 * Reassignments are resolved in source order, so a reassignment inside one
 * branch counts as fresh for the code after it.
 */

const FUNCTION_TYPES = new Set([
  'FunctionDeclaration',
  'FunctionExpression',
  'ArrowFunctionExpression',
]);
const LOOP_TYPES = new Set([
  'ForStatement',
  'ForInStatement',
  'ForOfStatement',
  'WhileStatement',
  'DoWhileStatement',
]);
const PROMISE_CALLBACK_METHODS = new Set(['then', 'catch', 'finally']);

/** `useStore.getState()` */
function isGetStateCall(node) {
  return (
    node?.type === 'CallExpression' &&
    node.callee.type === 'MemberExpression' &&
    !node.callee.computed &&
    node.callee.object.type === 'Identifier' &&
    node.callee.object.name === 'useStore' &&
    node.callee.property.type === 'Identifier' &&
    node.callee.property.name === 'getState'
  );
}

function enclosingFunction(node) {
  for (let n = node.parent; n; n = n.parent) {
    if (FUNCTION_TYPES.has(n.type)) return n;
  }
  return null; // module scope
}

/** The callee of a call, looking through `a?.b()` chains. */
function isCallee(node) {
  const parent = node.parent;
  if (parent?.type === 'CallExpression' && parent.callee === node) return true;
  return parent?.type === 'ChainExpression' && isCallee(parent);
}

function isPromiseCallback(fn) {
  const call = fn.parent;
  if (call?.type !== 'CallExpression' || !call.arguments.includes(fn)) return false;
  const callee = call.callee;
  return (
    callee.type === 'MemberExpression' &&
    !callee.computed &&
    callee.property.type === 'Identifier' &&
    PROMISE_CALLBACK_METHODS.has(callee.property.name)
  );
}

/** The functions from the read's own up to (and including) the snapshot's. */
function functionChain(read, snapshotFn) {
  const chain = [];
  for (let fn = enclosingFunction(read); ; fn = enclosingFunction(fn)) {
    chain.push(fn);
    if (fn === snapshotFn || fn === null) return chain;
  }
}

function inside(node, outer) {
  return node.range[0] >= outer.range[0] && node.range[1] <= outer.range[1];
}

/** What a reference reads, or null when it is a call, a write or not a field read. */
function staleCandidate(ref, kind) {
  const id = ref.identifier;
  if (!ref.isRead() || ref.isWrite()) return null;
  if (kind === 'binding') return isCallee(id) ? null : id;
  const member = id.parent;
  if (member?.type !== 'MemberExpression' || member.object !== id) return null;
  if (isCallee(member)) return null;
  const parent = member.parent;
  if (parent?.type === 'AssignmentExpression' && parent.left === member) return null;
  return member;
}

/** @type {import('eslint').Rule.RuleModule} */
export default {
  meta: {
    type: 'problem',
    docs: {
      description: 'Disallow reading store state from a useStore.getState() snapshot after an await (F2)',
    },
    schema: [],
    messages: {
      stale:
        "'{{name}}' comes from a useStore.getState() snapshot taken before an await " +
        '(or read in a promise callback); re-read useStore.getState() here (F2).',
    },
  },
  create(context) {
    const sourceCode = context.sourceCode;
    /** await expressions grouped by the function that owns them */
    const awaitsByFn = new Map();
    /** [{ variable, kind, fn }] */
    const snapshots = [];

    function recordAwait(node) {
      const fn = enclosingFunction(node);
      if (!awaitsByFn.has(fn)) awaitsByFn.set(fn, []);
      awaitsByFn.get(fn).push(node);
    }

    function isStale(read, snapshotPoint, snapshotFn) {
      const chain = functionChain(read, snapshotFn);
      // The read is not inside the snapshot's function (e.g. a hoisted helper)
      if (chain[chain.length - 1] !== snapshotFn) return false;
      if (chain.slice(0, -1).some(isPromiseCallback)) return true;
      const loops = [];
      for (let n = read.parent; n && n !== snapshotFn; n = n.parent) {
        if (LOOP_TYPES.has(n.type) && n.range[0] >= snapshotPoint.range[1]) loops.push(n);
      }
      return chain.some((fn) =>
        (awaitsByFn.get(fn) ?? []).some(
          (aw) =>
            aw.range[0] >= snapshotPoint.range[1] &&
            (aw.range[1] <= read.range[0] || loops.some((loop) => inside(aw, loop)))
        )
      );
    }

    /** The latest assignment before the read, in source order. */
    function snapshotPointFor(variable, read) {
      let point = null;
      for (const ref of variable.references) {
        if (ref.isWrite() && ref.identifier.range[1] <= read.range[0]) {
          if (!point || ref.identifier.range[0] > point.range[0]) point = ref.identifier;
        }
      }
      return point;
    }

    /** The write's value is getState() (covers declarations, destructuring, reassignment). */
    function freshAssignment(ref) {
      return isGetStateCall(ref.writeExpr);
    }

    function check(variable, kind, fn) {
      for (const ref of variable.references) {
        const read = staleCandidate(ref, kind);
        if (!read) continue;
        const point = snapshotPointFor(variable, read);
        // Reassigned from something else than getState(): not a snapshot any more
        const pointRef = point && variable.references.find((r) => r.identifier === point);
        if (!pointRef || !freshAssignment(pointRef)) continue;
        if (isStale(read, point, fn)) {
          context.report({ node: read, messageId: 'stale', data: { name: sourceCode.getText(read) } });
        }
      }
    }

    return {
      AwaitExpression: recordAwait,
      'ForOfStatement[await=true]': recordAwait,
      VariableDeclarator(node) {
        if (!isGetStateCall(node.init)) return;
        if (node.id.type !== 'Identifier' && node.id.type !== 'ObjectPattern') return;
        const kind = node.id.type === 'Identifier' ? 'whole' : 'binding';
        const fn = enclosingFunction(node);
        for (const variable of sourceCode.getDeclaredVariables(node)) {
          snapshots.push({ variable, kind, fn });
        }
      },
      'Program:exit'() {
        for (const { variable, kind, fn } of snapshots) check(variable, kind, fn);
      },
    };
  },
};
