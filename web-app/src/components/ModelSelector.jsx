import React from 'react';

const models = [
    { id: 'nano_banana', name: 'Nano Banana (Flash)', desc: 'Быстро • Экономно' },
    { id: 'nano_banana_pro', name: 'Nano Banana Pro', desc: 'Высокое качество • Умно' },
    { id: 'imagen', name: 'Imagen', desc: 'Фотореализм' },
];

function ModelSelector({ value, onChange }) {
    return (
        <div className="model-selector">
            <h3>Выберите модель</h3>
            <div className="cards">
                {models.map((model) => (
                    <div
                        key={model.id}
                        className={`card ${value === model.id ? 'selected' : ''}`}
                        onClick={() => onChange(model.id)}
                    >
                        <div className="card-name">{model.name}</div>
                        <div className="card-desc">{model.desc}</div>
                    </div>
                ))}
            </div>
        </div>
    );
}

export default ModelSelector;
