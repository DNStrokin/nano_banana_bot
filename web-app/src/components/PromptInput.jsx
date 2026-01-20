import React from 'react';

function PromptInput({ prompt, onPromptChange, showReferenceUpload, useReference, onToggleReference }) {
    return (
        <div className="prompt-input">
            <h3>Ваша идея</h3>
            <textarea
                placeholder="Опишите вашу банановую мечту..."
                value={prompt}
                onChange={(e) => onPromptChange(e.target.value)}
                rows={4}
            />
            {showReferenceUpload && (
                <div className="upload-section">
                    <button
                        className={`secondary-btn ${useReference ? 'active' : ''}`}
                        onClick={() => onToggleReference(!useReference)}
                        style={{
                            backgroundColor: useReference ? '#F4D03F' : '#333',
                            color: useReference ? '#000' : '#fff',
                            border: '1px solid #F4D03F'
                        }}
                    >
                        {useReference ? "✅ Референсы включены" : "📷 Добавить референс"}
                    </button>
                    {useReference && <div style={{ fontSize: '0.8em', color: '#aaa', marginTop: '5px' }}>Бот попросит отправить фото в чате</div>}
                </div>
            )}
        </div>
    );
}

export default PromptInput;
