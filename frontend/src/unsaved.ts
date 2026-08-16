/** 全局「未保存修改」标记：档案编辑器写入，页面切换/关闭前消费。 */

type Listener = (dirty: boolean) => void;

let dirty = false;
const listeners = new Set<Listener>();

/** 档案编辑器调用：用户编辑置 true，保存成功/重置置 false。 */
export function setUnsaved(value: boolean): void {
  dirty = value;
  listeners.forEach((l) => l(value));
}

export function getUnsaved(): boolean {
  return dirty;
}

export function subscribeUnsaved(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
