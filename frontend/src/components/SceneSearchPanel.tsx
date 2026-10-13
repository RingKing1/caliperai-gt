import React, { useState } from 'react';
import {
  sceneApi,
  type HybridSceneResult,
  type HybridSceneSearchResponse,
} from '@/api/client';

interface SceneSearchPanelProps {
  datasetId?: string;
  /** Called when a result row is clicked (e.g. expand/scroll to the scene). */
  onSelectScene?: (sceneId: string) => void;
}

interface GroupChip {
  key: string;
  label: string;
  hint: string;
}

const GROUP_CHIPS: GroupChip[] = [
  { key: 'vehicle', label: '机动车', hint: 'car/truck/bus/trailer' },
  { key: 'two_wheeler', label: '二轮车', hint: 'motorcycle/bicycle' },
  { key: 'vru', label: '行人', hint: 'pedestrian' },
  { key: 'static_obstacle', label: '静态障碍', hint: 'barrier/cone' },
];

const CAMERA_OPTIONS = [
  { key: 'front', label: '前视' },
  { key: 'left_front', label: '左前' },
  { key: 'right_front', label: '右前' },
  { key: 'back', label: '后视' },
  { key: 'left_back', label: '左后' },
  { key: 'right_back', label: '右后' },
];

const SEMANTIC_SUGGESTIONS = ['堵车', '雨夜路口', '施工路段', '高速公路', '停车场'];

function shortSceneName(name: string): string {
  // data_20260910_061820_transfusion_sweep5 -> 061820
  const parts = name.split('_');
  return parts.length > 2 ? parts[2] : name;
}

const REASON_LABELS: Record<string, string> = {
  vehicle: '机动车',
  two_wheeler: '二轮车',
  vru: '行人',
  static_obstacle: '静态障碍',
};

function reasonLabel(reason: string): string {
  const [kind, value] = reason.split(':');
  if (kind === 'group') return REASON_LABELS[value] ?? value;
  return value;
}

export const SceneSearchPanel: React.FC<SceneSearchPanelProps> = ({
  datasetId,
  onSelectScene,
}) => {
  const [semanticQuery, setSemanticQuery] = useState('');
  const [selectedGroups, setSelectedGroups] = useState<string[]>([]);
  const [selectedCameras, setSelectedCameras] = useState<string[]>(['front']);
  const [minGroupRatio, setMinGroupRatio] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<HybridSceneSearchResponse | null>(null);

  const toggleGroup = (key: string) => {
    setSelectedGroups((prev) =>
      prev.includes(key) ? prev.filter((g) => g !== key) : [...prev, key],
    );
  };

  const toggleCamera = (key: string) => {
    setSelectedCameras((prev) =>
      prev.includes(key) ? prev.filter((c) => c !== key) : [...prev, key],
    );
  };

  const runSearch = async () => {
    const semantic = semanticQuery.trim();
    if (!semantic && selectedGroups.length === 0) {
      setError('请输入语义描述，或至少选择一个类别条件');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await sceneApi.searchHybrid({
        dataset_id: datasetId,
        semantic_q: semantic || undefined,
        groups: selectedGroups.length ? selectedGroups : undefined,
        cameras: semantic && selectedCameras.length ? selectedCameras : undefined,
        min_group_ratio:
          selectedGroups.length && minGroupRatio > 0
            ? minGroupRatio / 100
            : undefined,
        min_similarity: semantic ? 0.0 : undefined,
        page_size: 50,
      });
      setResponse(result);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(
        typeof detail === 'string'
          ? detail
          : Array.isArray(detail)
            ? detail.map((d: any) => d.msg).join('; ')
            : '搜索失败，请检查后端服务',
      );
    } finally {
      setLoading(false);
    }
  };

  const reset = () => {
    setSemanticQuery('');
    setSelectedGroups([]);
    setMinGroupRatio(0);
    setResponse(null);
    setError(null);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') void runSearch();
  };

  return (
    <div className="mb-4 rounded-xl border border-gray-700/50 bg-gray-800/40 p-3">
      {/* Semantic input */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-cyan-400">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M21 21l-4.35-4.35M17 11a6 6 0 11-12 0 6 6 0 0112 0z" />
            </svg>
          </span>
          <input
            value={semanticQuery}
            onChange={(e) => setSemanticQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="语义搜场景：堵车 / 雨夜路口 / 施工路段（可留空，仅按类别过滤）"
            className="w-full pl-9 pr-3 py-2 text-sm bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-cyan-500"
          />
        </div>
        <button
          onClick={() => void runSearch()}
          disabled={loading}
          className="px-4 py-2 text-sm font-medium rounded-lg bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white"
        >
          {loading ? '搜索中…' : '搜索场景'}
        </button>
        {(response || semanticQuery || selectedGroups.length > 0) && (
          <button onClick={reset} className="px-2 py-2 text-xs text-gray-400 hover:text-white">
            清空
          </button>
        )}
      </div>

      {/* Suggestions */}
      {!response && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-gray-500">试试：</span>
          {SEMANTIC_SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => setSemanticQuery(s)}
              className="px-2 py-0.5 text-[11px] rounded-full bg-gray-900/60 border border-gray-700 text-gray-300 hover:border-cyan-500 hover:text-cyan-300"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Label filters */}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="text-[11px] text-gray-500 uppercase">精确过滤</span>
        {GROUP_CHIPS.map((chip) => {
          const active = selectedGroups.includes(chip.key);
          return (
            <button
              key={chip.key}
              onClick={() => toggleGroup(chip.key)}
              title={chip.hint}
              className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                active
                  ? 'bg-cyan-500/20 border-cyan-400 text-cyan-200'
                  : 'bg-gray-900/60 border-gray-700 text-gray-300 hover:border-gray-500'
              }`}
            >
              {chip.label}
            </button>
          );
        })}
        {selectedGroups.length > 0 && (
          <label className="flex items-center gap-1.5 text-[11px] text-gray-400 ml-1">
            最小占比
            <input
              type="range"
              min={0}
              max={50}
              step={5}
              value={minGroupRatio}
              onChange={(e) => setMinGroupRatio(Number(e.target.value))}
              className="w-20 accent-cyan-500"
            />
            <span className="w-10 text-cyan-300">{minGroupRatio}%</span>
          </label>
        )}
        {semanticQuery.trim() && (
          <span className="flex items-center gap-1 ml-1">
            <span className="text-[11px] text-gray-500">相机</span>
            {CAMERA_OPTIONS.map((cam) => {
              const active = selectedCameras.includes(cam.key);
              return (
                <button
                  key={cam.key}
                  onClick={() => toggleCamera(cam.key)}
                  className={`px-1.5 py-0.5 text-[10px] rounded border ${
                    active
                      ? 'border-cyan-400 text-cyan-200 bg-cyan-500/10'
                      : 'border-gray-700 text-gray-500 hover:text-gray-300'
                  }`}
                >
                  {cam.label}
                </button>
              );
            })}
          </span>
        )}
      </div>

      {error && (
        <div className="mt-2 text-xs text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {/* Results */}
      {response && (
        <div className="mt-3">
          <div className="flex items-center gap-2 text-[11px] text-gray-500 mb-2">
            <span>
              模式：
              <span className={response.mode === 'hybrid' ? 'text-cyan-300' : 'text-emerald-300'}>
                {response.mode === 'hybrid' ? '标签过滤 + 语义排序' : '纯标签过滤'}
              </span>
            </span>
            <span>命中 {response.total} 个场景</span>
          </div>
          {response.results.length === 0 ? (
            <div className="text-sm text-gray-500 py-4 text-center">
              没有满足条件的场景，可降低占比阈值或放宽语义条件
            </div>
          ) : (
            <div className="space-y-1.5">
              {response.results.map((row: HybridSceneResult) => (
                <button
                  key={row.scene_id}
                  onClick={() => onSelectScene?.(row.scene_id)}
                  className="w-full text-left rounded-lg border border-gray-700/60 bg-gray-900/50 hover:border-cyan-500/60 hover:bg-gray-900 p-2.5 transition-colors"
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-white">
                      {shortSceneName(row.scene_name)}
                    </span>
                    {typeof row.semantic_score === 'number' && (
                      <span className="px-1.5 py-0.5 text-[10px] rounded bg-cyan-500/20 text-cyan-200 border border-cyan-500/40">
                        语义 {row.semantic_score.toFixed(3)}
                      </span>
                    )}
                    <span className="px-1.5 py-0.5 text-[10px] rounded bg-gray-700/50 text-gray-300">
                      {row.label_profile?.total_objects?.toLocaleString?.() ?? row.label_profile?.total_objects} 框
                    </span>
                    {row.label_profile?.primary_class && (
                      <span className="text-[10px] text-gray-400">
                        主类别 {row.label_profile.primary_class}
                      </span>
                    )}
                    <span className="ml-auto text-[10px] text-gray-500">
                      {row.frame_count?.toLocaleString?.()} 帧 · 点击定位
                    </span>
                  </div>
                  <div className="mt-1.5 flex items-center gap-1.5 flex-wrap">
                    {row.matched_reasons?.map((reason) => (
                      <span
                        key={reason}
                        className="px-1.5 py-0.5 text-[10px] rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/30"
                      >
                        ✓ {reasonLabel(reason)}
                      </span>
                    ))}
                    {row.preview_frames && row.preview_frames.length > 0 && (
                      <span className="flex items-center gap-1.5 ml-auto">
                        {row.preview_frames.slice(0, 3).map((pf) => (
                          <img
                            key={`${pf.frame_index}-${pf.camera}`}
                            src={sceneApi.frameImageUrl(row.scene_id, pf.frame_index, pf.camera, 240)}
                            alt={`frame ${pf.frame_index} ${pf.camera}`}
                            title={`#${pf.frame_index} ${pf.camera} · 相似度 ${pf.similarity.toFixed(3)}`}
                            loading="lazy"
                            className="w-24 h-[54px] object-cover rounded border border-gray-700 hover:border-cyan-400"
                          />
                        ))}
                      </span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
