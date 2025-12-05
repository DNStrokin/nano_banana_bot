import React from 'react';



function Settings({ model, aspectRatio, onAspectRatioChange, resolution, onResolutionChange, allowHighRes = true }) {
    return (
        <div className="settings">
            <h3>Настройки</h3>
            <div className="setting-row">
                <label>Соотношение сторон</label>
                <div className="custom-select-wrapper">
                    <select
                        value={aspectRatio}
                        onChange={(e) => onAspectRatioChange(e.target.value)}
                    >
                        {["1:1", "4:3", "3:4", "16:9", "9:16", "2:3", "3:2", "4:5", "5:4", "21:9"].map(r => (
                            <option key={r} value={r}>{r}</option>
                        ))}
                    </select>
                </div>
            </div>

            {model === 'nano_banana_pro' && (
                <div className="setting-row" style={{ marginTop: '15px' }}>
                    <label>Разрешение</label>
                    <div className="chips">
                        {[
                            { val: "1K", label: "Standard (1K)" },
                            { val: "2K", label: "High Res (2K)" },
                            { val: "4K", label: "Ultra Res (4K)" }
                        ].map((opt) => {
                            const isLocked = !allowHighRes && opt.val !== '1K';
                            return (
                                <button
                                    key={opt.val}
                                    className={`chip ${resolution === opt.val ? 'active' : ''}`}
                                    onClick={() => !isLocked && onResolutionChange(opt.val)}
                                    style={{ opacity: isLocked ? 0.5 : 1, cursor: isLocked ? 'not-allowed' : 'pointer' }}
                                >
                                    {opt.label} {isLocked ? '🔒' : ''}
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
}

export default Settings;
