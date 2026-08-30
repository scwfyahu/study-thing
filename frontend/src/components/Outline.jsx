import React from "react";

function buildTree(content) {
  const lines = (content || "").split("\n");
  const root = { children: [] };
  const stack = [{ depth: -1, children: root.children }];

  for (const raw of lines) {
    const text = raw.replace(/\s+$/, "");
    if (!text.trim()) continue;
    const indent = text.match(/^ */)[0].length;
    const depth = Math.round(indent / 2);
    const node = { text: text.trim(), children: [] };
    while (stack.length > 1 && depth <= stack[stack.length - 1].depth) stack.pop();
    if (depth > stack[stack.length - 1].depth) {
      stack[stack.length - 1].children[stack[stack.length - 1].children.length - 1]?.children.push(node);
    } else {
      stack[stack.length - 1].children.push(node);
    }
    stack.push({ depth, children: node.children });
  }
  return root.children;
}

function Node({ node }) {
  return (
    <li>
      <span className="ol-text">{node.text}</span>
      {node.children.length > 0 && (
        <ul className="ol-children">{node.children.map((c, i) => <Node key={i} node={c} />)}</ul>
      )}
    </li>
  );
}

export default function Outline({ content }) {
  const tree = buildTree(content);
  if (!tree.length) return <p className="muted">Empty.</p>;
  return (
    <div className="outline">
      <ul className="ol-root">{tree.map((n, i) => <Node key={i} node={n} />)}</ul>
    </div>
  );
}