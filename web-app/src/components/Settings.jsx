import React from 'react';

const ratios = ["1:1", "16:9", "9:16", "4:3", "3:4"];

function Settings({ model, aspectRatio, onAspectRatioChange, resolution, onResolutionChange }) {
    return (
        <div className="settings">
            <h3>Настройки</h3>
            <div className="setting-row">
                <label>Соотношение сторон</label>
                <div className="chips">
                    {ratios.map((r) => (
                        <button
                            key={r}
                            className={`chip ${aspectRatio === r ? 'active' : ''}`}
                            onClick={() => onAspectRatioChange(r)}
                        >
                            {r}
                        </button>
                    ))}
                </div>
            </div>

            {model === 'nano_banana_pro' && (
                <div className="setting-row" style={{ marginTop: '15px' }}>
                    <label>Разрешение</label>
                    <div className="chips">
                        {[
                            { val: "1024x1024", label: "Standard (1K)" },
                            { val: "2048x2048", label: "High Res (2K)" },
                            { val: "4096x4096", label: "Ultra Res (4K)" }
                        ].map((opt) => (
                            <button
                                key={opt.val}
                                className={`chip ${resolution === opt.val ? 'active' : ''}`}
                                onClick={() => onResolutionChange(opt.val)}
                            >
                                {opt.label}
                            </button>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

export default Settings;
