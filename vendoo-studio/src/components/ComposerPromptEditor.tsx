import { Extension, Node, type JSONContent } from "@tiptap/core";
import Placeholder from "@tiptap/extension-placeholder";
import {
  EditorContent,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  useEditor,
  type NodeViewProps,
} from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  createContext,
  use,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  type RefObject,
} from "react";
import { CitationChip } from "./CitationChip";
import { ChatCitationRevealContext } from "./chatCitationContext";
import { serializeChatCitation, type ChatCitation } from "./chatCitations";
import {
  CITATION_NODE,
  citationNode,
  docToPrompt,
  promptToDoc,
  type ComposerNode,
} from "./composerDoc";

export interface ComposerPromptEditorHandle {
  /** Drops a quote in at the caret, as T3 Code's composer does. */
  insertCitation: (citation: ChatCitation) => void;
  focus: () => void;
}

const ComposerSubmitContext = createContext<(() => void) | null>(null);

const asContent = (doc: ComposerNode) => doc as unknown as JSONContent;

/** The chip is one atom: the caret steps over it and Backspace removes it whole. */
const CitationExtension = Node.create({
  name: CITATION_NODE,
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  addAttributes() {
    return {
      citation: { default: null },
      source: { default: "" },
    };
  },
  parseHTML() {
    return [{ tag: "span[data-composer-citation]" }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["span", { "data-composer-citation": "", ...HTMLAttributes }];
  },
  addNodeView() {
    return ReactNodeViewRenderer(CitationNodeView);
  },
});

function CitationNodeView({ node, editor, getPos }: NodeViewProps) {
  const reveal = use(ChatCitationRevealContext);
  const submit = use(ComposerSubmitContext);
  const citation = node.attrs.citation as ChatCitation | null;

  const nodePos = useCallback(() => {
    const pos = typeof getPos === "function" ? getPos() : null;
    return typeof pos === "number" ? pos : null;
  }, [getPos]);

  const replaceCitation = useCallback(
    (next: ChatCitation) => {
      if (!editor.isEditable) return;
      const pos = nodePos();
      if (pos === null) return;
      const current = editor.state.doc.nodeAt(pos);
      if (!current || current.type.name !== CITATION_NODE) return;
      editor.view.dispatch(
        editor.state.tr.setNodeMarkup(pos, undefined, {
          ...current.attrs,
          citation: next,
          source: serializeChatCitation(next),
        }),
      );
    },
    [editor, nodePos],
  );

  const remove = useCallback(() => {
    if (!editor.isEditable) return;
    const pos = nodePos();
    if (pos === null) return;
    const current = editor.state.doc.nodeAt(pos);
    if (!current) return;
    editor.chain().focus().deleteRange({ from: pos, to: pos + current.nodeSize }).run();
  }, [editor, nodePos]);

  if (!citation) return null;
  return (
    <NodeViewWrapper
      as="span"
      className="composer-citation-node"
      contentEditable={false}
      spellCheck={false}
      data-composer-citation-chip="true"
    >
      <CitationChip
        citation={citation}
        composer
        onReveal={(quoted) => reveal?.(quoted)}
        onRemove={remove}
        onComment={replaceCitation}
        onCommentAndSend={(next) => {
          replaceCitation(next);
          submit?.();
        }}
      />
    </NodeViewWrapper>
  );
}

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder: string;
  handleRef: RefObject<ComposerPromptEditorHandle | null>;
}

/**
 * The composer, modelled on T3 Code's: plain text with cited quotes sitting
 * inline as chips exactly where the seller dropped them, serialized back to a
 * markdown prompt whose quotes are links.
 */
export function ComposerPromptEditor({ value, onChange, onSubmit, placeholder, handleRef }: Props) {
  const submitRef = useRef(onSubmit);
  submitRef.current = onSubmit;

  const extensions = useMemo(
    () => [
      StarterKit.configure({
        // Prose formatting belongs to the reply, not the seller's prompt: the
        // composer stays plain text plus chips.
        blockquote: false,
        bold: false,
        bulletList: false,
        code: false,
        codeBlock: false,
        heading: false,
        horizontalRule: false,
        italic: false,
        listItem: false,
        orderedList: false,
        strike: false,
        link: false,
        underline: false,
      }),
      CitationExtension,
      Placeholder.configure({ placeholder }),
      Extension.create({
        name: "composer-submit",
        addKeyboardShortcuts: () => ({
          Enter: () => {
            submitRef.current();
            return true;
          },
        }),
      }),
    ],
    [placeholder],
  );

  const editor = useEditor(
    {
      extensions,
      content: asContent(promptToDoc(value)),
      editorProps: { attributes: { class: "chat-composer-input", "aria-label": "Message" } },
      onUpdate: ({ editor: instance }) => onChange(docToPrompt(instance.getJSON() as ComposerNode)),
    },
    [extensions],
  );

  // A send that clears the box, or a queued message put back, arrives as a new
  // value; anything the editor itself produced already matches.
  useEffect(() => {
    if (!editor) return;
    if (docToPrompt(editor.getJSON() as ComposerNode) === value) return;
    editor.commands.setContent(asContent(promptToDoc(value)), { emitUpdate: false });
  }, [editor, value]);

  useImperativeHandle(
    handleRef,
    () => ({
      insertCitation: (citation) => {
        if (!editor) return;
        // The quote lands at the caret, or at the end when the seller cited
        // without ever putting the caret in the box. T3 Code keeps a boundary
        // around it so the chip never fuses onto the word before it.
        const { state } = editor;
        const at = editor.isFocused ? state.selection.from : state.doc.content.size;
        const before = state.doc.textBetween(Math.max(0, at - 1), at, "\n", " ");
        const content: JSONContent[] = [];
        if (before && !/\s$/.test(before)) content.push({ type: "text", text: " " });
        content.push(asContent(citationNode(citation)), { type: "text", text: " " });
        editor.chain().focus().insertContentAt(at, content).run();
      },
      focus: () => editor?.commands.focus(),
    }),
    [editor],
  );

  return (
    <ComposerSubmitContext value={onSubmit}>
      <EditorContent editor={editor} className="chat-composer-editor" />
    </ComposerSubmitContext>
  );
}
