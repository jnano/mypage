import type { ImageView } from "@/lib/blocks/types";

// 블록 그림(홈블록 설계도 §4.4.2) — 썸네일 전이면 원본 대신 크기가 고정된 자리 표시. 장식 그림(빈 alt)은 읽지 않는다
export function BlockImage({ image, sizes = "(max-width: 640px) 100vw, 640px" }: { image: ImageView; sizes?: string }) {
  const size = { width: image.width ?? undefined, height: image.height ?? undefined };
  if (image.pending) {
    // 크기는 스킨이 자리를 잡도록 data-* 로(span 에는 width·height 속성이 없다)
    const box = { "data-slot": "image-pending", "data-width": image.width ?? undefined, "data-height": image.height ?? undefined };
    return image.alt ? <span role="img" aria-label={image.alt} {...box} /> : <span aria-hidden="true" {...box} />;
  }
  return <img src={image.src} srcSet={image.srcset} sizes={sizes} alt={image.alt} {...size} loading="lazy" decoding="async" />;
}
