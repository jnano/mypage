"use client";

// 동영상 노드 — 저장 형태 <div data-embed="youtube" data-video-id="…"></div>(§8.2, iframe 저장 안 함)
// 편집 화면은 iframe 없이 자리 표시만 한다. 읽기 화면의 iframe 은 서버 렌더(content_rendered)가 만든다.
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import {
  $getNodeByKey,
  DecoratorNode,
  type DOMConversionMap,
  type DOMExportOutput,
  type LexicalNode,
  type NodeKey,
  type SerializedLexicalNode,
  type Spread,
} from "lexical";
import type { ReactNode } from "react";
import { editorTokens, type VideoProvider } from "@/lib/editor/tokens";

export type SerializedVideoNode = Spread<{ provider: VideoProvider; videoId: string }, SerializedLexicalNode>;

function isProvider(value: string | null): value is VideoProvider {
  return value !== null && Object.hasOwn(editorTokens.videoProviders, value);
}

function VideoView({ nodeKey, provider, videoId }: { nodeKey: NodeKey; provider: VideoProvider; videoId: string }) {
  const [editor] = useLexicalComposerContext();
  return (
    <figure data-slot="editor-video" data-embed={provider}>
      <span>
        {provider === "youtube" ? "YouTube" : provider} 동영상 · {videoId}
      </span>{" "}
      <button
        type="button"
        onClick={() =>
          editor.update(() => {
            const node = $getNodeByKey(nodeKey);
            if ($isVideoNode(node)) node.remove();
          })
        }
      >
        본문에서 빼기
      </button>
    </figure>
  );
}

export class VideoNode extends DecoratorNode<ReactNode> {
  __provider: VideoProvider;
  __videoId: string;

  static getType(): string {
    return "video-embed";
  }

  static clone(node: VideoNode): VideoNode {
    return new VideoNode(node.__provider, node.__videoId, node.__key);
  }

  constructor(provider: VideoProvider, videoId: string, key?: NodeKey) {
    super(key);
    this.__provider = provider;
    this.__videoId = videoId;
  }

  createDOM(): HTMLElement {
    return document.createElement("div");
  }

  updateDOM(): false {
    return false;
  }

  static importDOM(): DOMConversionMap | null {
    return {
      div: (el: HTMLElement) => {
        const provider = el.getAttribute("data-embed");
        const videoId = el.getAttribute("data-video-id");
        if (!isProvider(provider) || !videoId || !new RegExp(editorTokens.videoProviders[provider].idPattern).test(videoId)) return null;
        return { priority: 4, conversion: () => ({ node: $createVideoNode(provider, videoId) }) };
      },
    };
  }

  exportDOM(): DOMExportOutput {
    const div = document.createElement("div");
    div.setAttribute("data-embed", this.__provider);
    div.setAttribute("data-video-id", this.__videoId);
    return { element: div };
  }

  static importJSON(json: SerializedVideoNode): VideoNode {
    return $createVideoNode(json.provider, json.videoId);
  }

  exportJSON(): SerializedVideoNode {
    return { ...super.exportJSON(), provider: this.__provider, videoId: this.__videoId };
  }

  isInline(): false {
    return false;
  }

  decorate(): ReactNode {
    return <VideoView nodeKey={this.getKey()} provider={this.__provider} videoId={this.__videoId} />;
  }
}

export function $createVideoNode(provider: VideoProvider, videoId: string): VideoNode {
  return new VideoNode(provider, videoId);
}

export function $isVideoNode(node: LexicalNode | null | undefined): node is VideoNode {
  return node instanceof VideoNode;
}
