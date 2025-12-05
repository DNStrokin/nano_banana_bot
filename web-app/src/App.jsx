import React, { useState, useEffect } from 'react';
import ModelSelector from './components/ModelSelector';
import Settings from './components/Settings';
import PromptInput from './components/PromptInput';

function App() {
    const [model, setModel] = useState('nano_banana');
    const [prompt, setPrompt] = useState('');
    const [aspectRatio, setAspectRatio] = useState('1:1');
    const [resolution, setResolution] = useState('1K');
    const [useReference, setUseReference] = useState(false);
    const [userLevel, setUserLevel] = useState('demo');

    // Parse URL params on mount
    useEffect(() => {
        const params = new URLSearchParams(window.location.search);
        const lvl = params.get('level') || 'demo';
        setUserLevel(lvl);
    }, []);

    // Initialize Telegram WebApp
    useEffect(() => {
        const tg = window.Telegram?.WebApp;
        if (tg) {
            tg.ready();
            tg.MainButton.text = useReference ? "ДАЛЕЕ (ОТПРАВИТЬ ФОТО)" : "СГЕНЕРИРОВАТЬ";
            tg.MainButton.color = "#F4D03F";
            tg.MainButton.textColor = "#000000";

            // Setup MainButton visibility based on prompt
            if (prompt.trim().length > 0) {
                tg.MainButton.show();
            } else {
                tg.MainButton.hide();
            }

            // Handle MainButton click
            const handleMainBtn = () => {
                const data = {
                    action: 'generate',
                    model,
                    prompt,
                    aspect_ratio: aspectRatio,
                    resolution: resolution,
                    use_reference: useReference
                };
                tg.sendData(JSON.stringify(data));
            };

            tg.onEvent('mainButtonClicked', handleMainBtn);
            return () => {
                tg.offEvent('mainButtonClicked', handleMainBtn);
            };
        }
    }, [model, prompt, aspectRatio, resolution, useReference]);

    const allowHighRes = userLevel === 'full' || userLevel === 'admin';
    const canUploadPhoto = userLevel !== 'demo';

    return (
        <div className="app-container">
            <h1 style={{ textAlign: 'center', color: '#F4D03F' }}>🍌 Nano Banana</h1>

            <ModelSelector value={model} onChange={setModel} />

            <PromptInput
                prompt={prompt}
                onPromptChange={setPrompt}
                showReferenceUpload={model !== 'imagen' && canUploadPhoto} // Flash and Pro support it if level allows
                useReference={useReference}
                onToggleReference={setUseReference}
            />

            <Settings
                model={model}
                aspectRatio={aspectRatio}
                onAspectRatioChange={setAspectRatio}
                resolution={resolution}
                onResolutionChange={setResolution}
                allowHighRes={allowHighRes}
            />

        </div>
    );
}

export default App;
