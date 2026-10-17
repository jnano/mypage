import { BLOCKS, type BlockData, type BlockNode, type RenderableType } from "./types";

// 생성 파일의 견본(종류마다 해결된 모양 하나)을 블록 목록으로 — 개발 견본 화면용. 묶음·칸 나누기에는 견본 자식을 넣는다
const examples = BLOCKS.examples as unknown as BlockData;

function node<K extends RenderableType>(id: number, type: K, extra: Partial<BlockNode> = {}): BlockNode {
  return { id, type, data: examples[type], ...extra } as BlockNode;
}

export function exampleNodes(): BlockNode[] {
  const types = Object.keys(examples) as RenderableType[];
  let id = 0;
  return types.map((type) => {
    id += 1;
    if (type === "group") return node(id, type, { children: [node(1000 + id, "heading", {}), node(2000 + id, "text")] });
    if (type === "columns") return node(id, type, { columns: [[node(3000 + id, "text")], [node(4000 + id, "image")]] });
    return node(id, type);
  });
}
