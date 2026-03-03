// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  type ReactNode,
  type CSSProperties,
  type MutableRefObject,
} from "react";
import { useStickToBottom } from "use-stick-to-bottom";

import { ScrollArea } from "../ui/scroll-area";
import { cn } from "../../lib/utils";

export interface ScrollContainerProps {
  className?: string;
  children?: ReactNode;
  scrollShadow?: boolean;
  scrollShadowColor?: string;
  autoScrollToBottom?: boolean;
}

export interface ScrollContainerRef {
  scrollToBottom(): void;
}

export const ScrollContainer = forwardRef<ScrollContainerRef, ScrollContainerProps>(function ScrollContainer({
  className,
  children,
  scrollShadow = true,
  scrollShadowColor = "var(--background)",
  autoScrollToBottom = false,
}, ref) {
  const { scrollRef, contentRef, scrollToBottom, isAtBottom } =
    useStickToBottom({ initial: "instant" });
  useImperativeHandle(ref, () => ({
    scrollToBottom() {
      if (isAtBottom) {
        scrollToBottom();
      }
    },
  }));

  const tempScrollRef = useRef<HTMLElement | null>(null);
  const tempContentRef = useRef<HTMLElement | null>(null);
  const mutableScrollRef = scrollRef as MutableRefObject<HTMLElement | null>;
  const mutableContentRef = contentRef as MutableRefObject<HTMLElement | null>;
  useEffect(() => {
    if (!autoScrollToBottom) {
      tempScrollRef.current = mutableScrollRef.current;
      tempContentRef.current = mutableContentRef.current;
      mutableScrollRef.current = null;
      mutableContentRef.current = null;
    } else if (tempScrollRef.current && tempContentRef.current) {
      mutableScrollRef.current = tempScrollRef.current;
      mutableContentRef.current = tempContentRef.current;
    }
  }, [autoScrollToBottom, mutableContentRef, mutableScrollRef]);

  return (
    <div className={cn("relative", className)}>
      {scrollShadow && (
        <>
          <div
            className={cn(
              "absolute top-0 right-0 left-0 z-10 h-10 bg-gradient-to-t",
              `from-transparent to-[var(--scroll-shadow-color)]`,
            )}
            style={
              {
                "--scroll-shadow-color": scrollShadowColor,
              } as CSSProperties
            }
          ></div>
          <div
            className={cn(
              "absolute right-0 bottom-0 left-0 z-10 h-10 bg-gradient-to-b",
              `from-transparent to-[var(--scroll-shadow-color)]`,
            )}
            style={
              {
                "--scroll-shadow-color": scrollShadowColor,
              } as CSSProperties
            }
          ></div>
        </>
      )}
      <ScrollArea ref={scrollRef} className="h-full w-full">
        <div className="h-fit w-full" ref={contentRef}>
          {children}
        </div>
      </ScrollArea>
    </div>
  );
});
