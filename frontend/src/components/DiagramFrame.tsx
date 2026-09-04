import { useEffect, useRef, useState } from "react";

interface Props {
  src: string;
  title: string;
  caption: string;
  height?: number;
}

/**
 * Embeds one of the pre-rendered Archify artifacts.
 *
 * Each artifact is a ~700KB self-contained page, so the iframe is only mounted
 * once it scrolls into view — opening the tab should not pull 2MB straight
 * away, and a reader who never reaches the third diagram never downloads it.
 */
export default function DiagramFrame({ src, title, caption, height = 520 }: Props) {
  const holder = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = holder.current;
    if (!el || visible) return;

    if (!("IntersectionObserver" in window)) {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "300px" }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [visible]);

  return (
    <figure className="my-5">
      <div
        ref={holder}
        className="overflow-hidden rounded-xl border border-ink-700 bg-ink-900"
        style={{ height }}
      >
        {visible ? (
          <iframe
            src={src}
            title={title}
            loading="lazy"
            className="h-full w-full border-0"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-xs text-ink-600">
            loading diagram…
          </div>
        )}
      </div>
      <figcaption className="mt-2 flex items-baseline justify-between gap-3 text-xs text-ink-400">
        <span>{caption}</span>
        <a
          href={src}
          target="_blank"
          rel="noreferrer"
          className="shrink-0 text-accent-soft underline underline-offset-2 hover:text-accent"
        >
          open full screen ↗
        </a>
      </figcaption>
    </figure>
  );
}
