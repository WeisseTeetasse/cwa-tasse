/**
 * waits until queue is finished, meaning the book is done loading
 * @param callback
 */
function qFinished(callback){
    let timeout=setInterval(()=>{
        if (reader && reader.rendition && reader.rendition.q && reader.rendition.q.running === undefined) {
            clearInterval(timeout);
            callback();
        }
        },300
    )
}

function calculateProgress(){
    if (!reader || !reader.rendition || !reader.rendition.location || !reader.rendition.location.end) {
        return 0;
    }
    let data=reader.rendition.location.end;
    if (!data || !data.cfi || !epub || !epub.locations) {
        return 0;
    }
    return Math.round(epub.locations.percentageFromCfi(data.cfi)*100);
}

// register new event emitter locationchange that fires on urlchange
// source: https://stackoverflow.com/a/52809105/21941129
(() => {
    let oldPushState = history.pushState;
    history.pushState = function pushState() {
        let ret = oldPushState.apply(this, arguments);
        window.dispatchEvent(new Event('locationchange'));
        return ret;
    };

    let oldReplaceState = history.replaceState;
    history.replaceState = function replaceState() {
        let ret = oldReplaceState.apply(this, arguments);
        window.dispatchEvent(new Event('locationchange'));
        return ret;
    };

    window.addEventListener('popstate', () => {
        window.dispatchEvent(new Event('locationchange'));
    });
})();

// Gate localStorage writes until the initial restore step has decided where to
// place the cursor. Otherwise the reader's own start-of-book locationchange
// events fire BEFORE restore runs, calculateProgress() returns 0, and we
// persist "0" to localStorage. On the next restore that "0" is truthy and
// shadows the kosyncPercent hint forever — so a book that you have read to
// 12 percent on a Kobo / KOReader device opens at 0 percent in the webreader.
let restoreComplete = false;

window.addEventListener('locationchange',()=>{
    let newPos=calculateProgress();
    if (progressDiv) {
        progressDiv.textContent=newPos+"%";
    }
    if (!restoreComplete) {
        return;
    }
    // Save progress to localStorage per book. Don't store 0 — there's nothing
    // to restore from "you are at the start", and persisting 0 would shadow
    // any future kosync hint.
    if (window.calibre && window.calibre.bookUrl && newPos > 0) {
        let bookKey = window.calibre.bookUrl;
        localStorage.setItem("calibre.reader.progress." + bookKey, newPos);
    }
});

var epub=ePub(calibre.bookUrl)

let progressDiv=document.getElementById("progress");

qFinished(()=>{
    if (!epub || !epub.locations) {
        restoreComplete = true;
        return;
    }
    epub.locations.generate().then(()=> {
        // Choose the best starting position:
        //   1. local progress (you've read past 0% in the browser)
        //   2. kosync hint from the device (no browser progress yet)
        //   3. start of book
        // CWA bookmarks (the manual bookmark icon) are still respected via
        // window.calibre.bookmark — we just don't shadow the kosync hint with
        // them, since users typically expect "where I left off on my device"
        // not "where I last manually bookmarked".
        if (window.calibre && window.calibre.bookUrl && reader && reader.rendition) {
            let bookKey = window.calibre.bookUrl;
            // Treat missing / "0" / unparseable values as no local progress.
            let savedProgress = parseInt(localStorage.getItem("calibre.reader.progress." + bookKey) || "0", 10);
            let hasBookmark = window.calibre.bookmark && window.calibre.bookmark.length > 0;
            let kosyncPercent = parseFloat(window.calibre.kosyncPercent);
            let targetPercentage = null;
            if (savedProgress > 0) {
                targetPercentage = savedProgress / 100;
            } else if (!hasBookmark && !isNaN(kosyncPercent) && kosyncPercent > 0) {
                targetPercentage = kosyncPercent / 100;
            }
            if (targetPercentage !== null) {
                let cfi = epub.locations.cfiFromPercentage(targetPercentage);
                if (cfi) {
                    reader.rendition.display(cfi);
                }
            }
        }
        // From this point on, locationchange handlers may persist new positions.
        restoreComplete = true;
        window.dispatchEvent(new Event('locationchange'))
    });
})
